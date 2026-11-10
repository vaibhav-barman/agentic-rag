"""Modules 4, 6, 7 and 8 through the chat endpoint: filters, hybrid search +
reranking, text-to-SQL, web search and the document sub-agent."""

import json

import httpx
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.config import get_settings
from app.db import get_repo
from app.main import app
from app.services import llm, retrieval
from app.services.tools import sql as sql_tool
from app.services.tools import web as web_tool
from tests.fakes import FakeRepo, FakeStore, ScriptedLLM, ScriptedStructured, fake_embed
from tests.test_threads_chat import USER_A, USER_B, h, parse_sse

settings = get_settings()


@pytest.fixture
def store():
    return FakeStore()


@pytest.fixture
def client(store, monkeypatch):
    monkeypatch.setattr(llm, "embed", fake_embed)
    monkeypatch.setattr(settings, "rerank_enabled", False)
    monkeypatch.setattr(settings, "tavily_api_key", "")

    def repo_override(user=Depends(get_current_user)):
        repo = FakeRepo(store, user.id)
        store.last_repo = repo
        return repo

    app.dependency_overrides[get_repo] = repo_override
    yield TestClient(app)
    app.dependency_overrides.clear()


def add_doc(store, user, filename, chunks, metadata=None, content=None):
    repo = FakeRepo(store, user)
    doc = repo.create_document(filename)
    repo.insert_chunks(
        doc["id"],
        [{"chunk_index": i, "content": c, "embedding": [1.0, 1.0]} for i, c in enumerate(chunks)],
    )
    repo.update_document(
        doc["id"], status="completed", chunk_count=len(chunks), metadata=metadata or {}
    )
    if content is not None:
        repo.set_document_content(doc["id"], content)
    return doc


def call(name, **arguments):
    return [llm.ToolCall(id=f"call_{name}", name=name, arguments=json.dumps(arguments))]


def chat(client, monkeypatch, user, content, *replies):
    """Run one turn with a scripted model; returns (events, scripted llm, thread id)."""
    fake = ScriptedLLM(*replies)
    monkeypatch.setattr(llm, "stream_chat", fake.stream_chat)
    tid = client.post("/threads", headers=h(user), json={}).json()["id"]
    r = client.post(f"/threads/{tid}/chat", headers=h(user), json={"content": content})
    return parse_sse(r.text), fake, tid


def named(events, name):
    return [d for e, d in events if e == name]


# --- Module 4: metadata filters ------------------------------------------------


def test_file_search_passes_metadata_filters(client, store, monkeypatch):
    add_doc(store, USER_A, "q3.md", ["Revenue grew 12%."], {"document_type": "report"})
    add_doc(store, USER_A, "todo.md", ["Buy milk."], {"document_type": "notes"})
    events, fake, _ = chat(
        client,
        monkeypatch,
        USER_A,
        "What do my reports say about pricing?",
        call("file_search", query="revenue", document_type="report", topic=" Pricing "),
        "Revenue grew.",
    )
    # The tool schema only offers document types the user actually has.
    schema = fake.calls[0]["tools"][0]["function"]["parameters"]["properties"]
    assert schema["document_type"]["enum"] == ["notes", "report"]

    first = store.last_repo.search_calls[0]
    assert first["metadata_filter"] == {"document_type": "report", "topics": ["pricing"]}
    # Nothing is tagged "pricing", so the tool retried without filters and said so.
    assert len(store.last_repo.search_calls) == 2
    assert store.last_repo.search_calls[1]["metadata_filter"] is None
    assert "Nothing matched the filters" in fake.calls[1]["messages"][-1]["content"]


def test_file_search_filter_limits_results(client, store, monkeypatch):
    add_doc(store, USER_A, "q3.md", ["Revenue grew 12%."], {"document_type": "report"})
    add_doc(store, USER_A, "todo.md", ["Buy milk."], {"document_type": "notes"})
    events, fake, _ = chat(
        client,
        monkeypatch,
        USER_A,
        "q",
        call("file_search", query="anything", document_type="notes"),
        "ok",
    )
    [sources] = named(events, "sources")
    assert [s["filename"] for s in sources["sources"]] == ["todo.md"]


# --- Module 6: hybrid search + reranking ---------------------------------------


def test_search_uses_hybrid_mode_and_asks_for_candidates(client, store, monkeypatch):
    add_doc(store, USER_A, "a.md", ["one", "two"])
    monkeypatch.setattr(settings, "rerank_enabled", True)
    monkeypatch.setattr(settings, "retrieval_candidates", 20)
    scripted = ScriptedStructured(
        {"rankings": [{"index": 0, "score": 0.1}, {"index": 1, "score": 0.95}]}
    )
    monkeypatch.setattr(llm, "complete_structured", scripted.complete_structured)
    events, _, _ = chat(client, monkeypatch, USER_A, "q", call("file_search", query="two"), "ok")

    search = store.last_repo.search_calls[0]
    assert search["mode"] == "hybrid" and search["match_count"] == 20
    assert search["query_text"] == "two"
    # Reranked: passage 1 first; passage 0 is under RERANK_MIN_SCORE and dropped.
    [sources] = named(events, "sources")
    assert [(s["chunk_index"], s["score"]) for s in sources["sources"]] == [(1, 0.95)]
    assert "Query: two" in scripted.calls[0]["messages"][-1]["content"]


def test_rerank_orders_caps_and_ignores_bad_indexes(monkeypatch):
    import asyncio

    sources = [{"filename": "f", "content": f"c{i}", "score": 0.01} for i in range(4)]
    scripted = ScriptedStructured(
        {
            "rankings": [
                {"index": 2, "score": 0.9},
                {"index": 0, "score": 0.5},
                {"index": 3, "score": 7},  # clamped to 1.0
                {"index": 99, "score": 1.0},  # not a passage
                {"index": 1, "score": 0.05},  # below the minimum
            ]
        }
    )
    monkeypatch.setattr(llm, "complete_structured", scripted.complete_structured)
    monkeypatch.setattr(settings, "rerank_min_score", 0.2)
    ranked = asyncio.run(retrieval.rerank("q", sources, top_k=2))
    assert [(s["content"], s["score"]) for s in ranked] == [("c3", 1.0), ("c2", 0.9)]


def test_rerank_failure_falls_back_to_fused_order(monkeypatch):
    import asyncio

    sources = [{"filename": "f", "content": f"c{i}", "score": 0.01} for i in range(4)]
    scripted = ScriptedStructured(RuntimeError("quota"))
    monkeypatch.setattr(llm, "complete_structured", scripted.complete_structured)
    ranked = asyncio.run(retrieval.rerank("q", sources, top_k=3))
    assert [s["content"] for s in ranked] == ["c0", "c1", "c2"]


def test_vector_mode_sends_similarity_threshold(client, store, monkeypatch):
    add_doc(store, USER_A, "a.md", ["one"])
    monkeypatch.setattr(settings, "search_mode", "vector")
    monkeypatch.setattr(settings, "retrieval_min_similarity", 0.42)
    chat(client, monkeypatch, USER_A, "q", call("file_search", query="one"), "ok")
    search = store.last_repo.search_calls[0]
    assert search["mode"] == "vector" and search["min_similarity"] == 0.42
    assert search["match_count"] == settings.file_search_top_k


# --- Module 7: text-to-SQL ------------------------------------------------------


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("delete from documents", "Only SELECT"),
        ("select 1; drop table documents", "single statement"),
        ("with x as (delete from documents returning *) select * from x", "read-only"),
        ("select * from auth.users", "public schema"),
        ("select pg_sleep(10)", "public schema"),
        ("select * into backup from documents", "read-only"),
        ("", "empty"),
    ],
)
def test_validate_sql_refuses(sql, reason):
    with pytest.raises(ValueError, match=reason):
        sql_tool.validate_sql(sql)


def test_validate_sql_accepts_selects():
    assert sql_tool.validate_sql(" select count(*) from documents; ") == (
        "select count(*) from documents"
    )
    sql_tool.validate_sql("WITH d AS (SELECT * FROM documents) SELECT updated_at FROM d")
    sql_tool.validate_sql("select metadata->>'document_type', count(*) from documents group by 1")


def test_query_database_round_trip(client, store, monkeypatch):
    add_doc(store, USER_A, "a.md", ["one"])
    rows = [{"document_type": "report", "n": 2, "embedding": [0.1], "note": "x" * 500}]
    ran: list[str] = []

    def run_sql(self, q):
        ran.append(q)
        return rows

    monkeypatch.setattr(FakeRepo, "run_sql", run_sql)
    query = (
        "select metadata->>'document_type' as document_type, count(*) as n "
        "from documents group by 1"
    )
    events, fake, tid = chat(
        client,
        monkeypatch,
        USER_A,
        "How many documents of each type do I have?",
        call("query_database", sql=query + ";"),
        "You have 2 reports.",
    )
    assert ran == [query]
    [result] = named(events, "tool_result")
    assert result["ok"] and result["summary"] == "1 row"
    assert result["data"]["sql"] == query and result["data"]["columns"] == [
        "document_type",
        "n",
        "note",
    ]
    tool_message = fake.calls[1]["messages"][-1]["content"]
    assert '"n": 2' in tool_message and "embedding" not in tool_message
    assert len(result["data"]["rows"][0]["note"]) == 301  # long cells are trimmed

    msgs = client.get(f"/threads/{tid}/messages", headers=h(USER_A)).json()
    assert msgs[-1]["steps"][0]["data"]["sql"] == query


def test_query_database_refuses_writes_without_touching_the_database(client, store, monkeypatch):
    add_doc(store, USER_A, "a.md", ["one"])
    events, fake, _ = chat(
        client,
        monkeypatch,
        USER_A,
        "Delete everything",
        call("query_database", sql="delete from documents"),
        "I can't do that.",
    )
    [result] = named(events, "tool_result")
    assert result["ok"] is False and "SELECT" in result["summary"]
    assert store.last_repo.sql_calls == []
    assert "Query refused" in fake.calls[1]["messages"][-1]["content"]


def test_query_database_reports_database_errors(client, store, monkeypatch):
    add_doc(store, USER_A, "a.md", ["one"])

    def boom(self, q):
        raise RuntimeError('column "nope" does not exist')

    monkeypatch.setattr(FakeRepo, "run_sql", boom)
    events, fake, _ = chat(
        client,
        monkeypatch,
        USER_A,
        "q",
        call("query_database", sql="select nope from documents"),
        "Sorry.",
    )
    assert named(events, "tool_result")[0]["ok"] is False
    assert "does not exist" in fake.calls[1]["messages"][-1]["content"]


# --- Module 7: web search -------------------------------------------------------


def test_web_search_not_offered_without_key(client, store, monkeypatch):
    add_doc(store, USER_A, "a.md", ["one"])
    _, fake, _ = chat(client, monkeypatch, USER_A, "hi", "hello")
    assert "web_search" not in [t["function"]["name"] for t in fake.calls[0]["tools"]]


def test_web_search_is_offered_alone_when_there_are_no_documents(client, monkeypatch):
    monkeypatch.setattr(settings, "tavily_api_key", "tvly-test")
    _, fake, _ = chat(client, monkeypatch, USER_A, "hi", "hello")
    assert [t["function"]["name"] for t in fake.calls[0]["tools"]] == ["web_search"]


def test_web_search_round_trip_with_attribution(client, store, monkeypatch):
    monkeypatch.setattr(settings, "tavily_api_key", "tvly-test")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Mars rover lands",
                        "url": "https://example.com/mars",
                        "content": "The rover landed on Tuesday.",
                        "score": 0.91,
                    },
                    {"title": "No url, skipped", "content": "x"},
                ]
            },
        )

    monkeypatch.setattr(web_tool, "transport", httpx.MockTransport(handler))
    events, fake, tid = chat(
        client,
        monkeypatch,
        USER_A,
        "When did the rover land?",
        call("web_search", query="mars rover landing date"),
        "It landed on Tuesday ([source](https://example.com/mars)).",
    )
    assert seen["auth"] == "Bearer tvly-test"
    assert seen["body"]["query"] == "mars rover landing date"
    [sources] = named(events, "sources")
    assert sources["sources"] == [
        {
            "type": "web",
            "title": "Mars rover lands",
            "url": "https://example.com/mars",
            "content": "The rover landed on Tuesday.",
            "score": 0.91,
        }
    ]
    assert "https://example.com/mars" in fake.calls[1]["messages"][-1]["content"]
    msgs = client.get(f"/threads/{tid}/messages", headers=h(USER_A)).json()
    assert msgs[-1]["sources"][0]["type"] == "web"
    assert msgs[-1]["sources"][0]["url"] == "https://example.com/mars"


def test_web_search_http_error_is_a_failed_step(client, monkeypatch):
    monkeypatch.setattr(settings, "tavily_api_key", "tvly-test")
    monkeypatch.setattr(
        web_tool, "transport", httpx.MockTransport(lambda request: httpx.Response(429))
    )
    events, _, _ = chat(client, monkeypatch, USER_A, "q", call("web_search", query="x"), "Sorry.")
    [result] = named(events, "tool_result")
    assert result["ok"] is False and result["summary"] == "Web search failed"
    assert events[-1][0] == "done"


def test_unknown_tool_and_tool_crash_do_not_break_the_turn(client, store, monkeypatch):
    add_doc(store, USER_A, "a.md", ["one"])

    async def boom(texts):
        raise RuntimeError("embeddings down")

    monkeypatch.setattr(llm, "embed", boom)
    events, fake, _ = chat(
        client,
        monkeypatch,
        USER_A,
        "q",
        call("not_a_tool"),
        call("file_search", query="x"),
        "Recovered.",
    )
    results = named(events, "tool_result")
    assert [r["ok"] for r in results] == [False, False]
    assert "Unknown tool" in results[0]["summary"] and "embeddings down" in results[1]["summary"]
    assert events[-1][0] == "done"


# --- Module 8: sub-agent --------------------------------------------------------

FULL_TEXT = (
    "# Handbook\n\nChapter one is about onboarding.\n\n# Finale\n\nThe last line says ZEBRA."
)


def test_analyze_document_runs_an_isolated_sub_agent(client, store, monkeypatch):
    doc = add_doc(
        store,
        USER_A,
        "handbook.md",
        ["Chapter one...", "The last line says ZEBRA."],
        content=FULL_TEXT,
    )
    fake = ScriptedLLM(
        "Noted.",  # turn 1 (main)
        call("analyze_document", document_id=doc["id"], task="Summarise the whole handbook."),
        call("read_passages", start=1, end=1),  # sub-agent uses its own tool
        "It covers onboarding and ends with ZEBRA.",  # sub-agent's answer
        "The handbook covers onboarding and ends with ZEBRA.",  # main agent's answer
    )
    monkeypatch.setattr(llm, "stream_chat", fake.stream_chat)
    tid = client.post("/threads", headers=h(USER_A), json={}).json()["id"]
    client.post(
        f"/threads/{tid}/chat", headers=h(USER_A), json={"content": "My secret word is PINEAPPLE."}
    )
    events = parse_sse(
        client.post(
            f"/threads/{tid}/chat", headers=h(USER_A), json={"content": "Summarise my handbook"}
        ).text
    )

    main_first, sub_first, sub_second, main_last = fake.calls[1:]
    # Isolation: the sub-agent sees the whole document and the task, and nothing of the chat.
    sub_text = json.dumps(sub_first["messages"])
    assert len(sub_first["messages"]) == 2
    assert "The last line says ZEBRA." in sub_text and "Summarise the whole handbook." in sub_text
    assert "PINEAPPLE" not in sub_text and "PINEAPPLE" in json.dumps(main_first["messages"])
    assert [t["function"]["name"] for t in sub_first["tools"]] == [
        "search_in_document",
        "read_passages",
    ]
    assert "[passage 1]" in sub_second["messages"][-1]["content"]
    # The main agent gets only the sub-agent's answer back, not the document.
    assert main_last["messages"][-1] == {
        "role": "tool",
        "tool_call_id": "call_analyze_document",
        "content": "It covers onboarding and ends with ZEBRA.",
    }
    assert "Chapter one is about onboarding" not in json.dumps(main_last["messages"])

    # Events: the sub-agent's step and text are tagged with the parent step id.
    calls = named(events, "tool_call")
    parent = next(c for c in calls if c["name"] == "analyze_document")
    child = next(c for c in calls if c["name"] == "read_passages")
    assert parent["parent_id"] is None and child["parent_id"] == parent["id"]
    sub_deltas = named(events, "subagent_delta")
    assert {d["parent_id"] for d in sub_deltas} == {parent["id"]}
    assert "".join(d["text"] for d in sub_deltas) == "It covers onboarding and ends with ZEBRA."
    # Only the main agent's text is the answer.
    assert "".join(d["text"] for d in named(events, "delta")) == (
        "The handbook covers onboarding and ends with ZEBRA."
    )
    order = [e for e, _ in events if e in {"tool_call", "tool_result"}]
    assert order == ["tool_call", "tool_call", "tool_result", "tool_result"]  # nested

    # Persisted so the nested view survives a reload.
    steps = client.get(f"/threads/{tid}/messages", headers=h(USER_A)).json()[-1]["steps"]
    by_name = {s["name"]: s for s in steps}
    assert by_name["analyze_document"]["text"] == "It covers onboarding and ends with ZEBRA."
    assert by_name["analyze_document"]["data"]["document"] == "handbook.md"
    assert by_name["read_passages"]["parent_id"] == by_name["analyze_document"]["id"]


def test_sub_agent_truncates_huge_documents_and_points_at_its_tools(client, store, monkeypatch):
    monkeypatch.setattr(settings, "subagent_max_chars", 40)
    doc = add_doc(store, USER_A, "big.md", ["a", "b"], content="START " + "x" * 200 + " END")
    events, fake, _ = chat(
        client,
        monkeypatch,
        USER_A,
        "Summarise big.md",
        call("analyze_document", document_id="big.md", task="Summarise."),  # by filename
        "Summary.",
        "Done.",
    )
    sub_prompt = fake.calls[1]["messages"][1]["content"]
    assert "START" in sub_prompt and "END" not in sub_prompt.split("</document>")[0]
    assert "read_passages" in sub_prompt
    result = next(r for r in named(events, "tool_result") if r["parent_id"] is None)
    assert result["data"]["truncated"] is True and doc["filename"] in result["summary"]


def test_sub_agent_rebuilds_text_from_chunks_for_older_documents(client, store, monkeypatch):
    add_doc(store, USER_A, "old.md", ["first part", "second part"])  # no stored full text
    _, fake, _ = chat(
        client,
        monkeypatch,
        USER_A,
        "q",
        call("analyze_document", document_id="old", task="Summarise."),
        "Summary.",
        "Done.",
    )
    assert "first part\n\nsecond part" in fake.calls[1]["messages"][1]["content"]


def test_analyze_document_cannot_reach_another_users_document(client, store, monkeypatch):
    theirs = add_doc(store, USER_B, "private.md", ["secret"], content="TOP SECRET")
    add_doc(store, USER_A, "mine.md", ["hello"], content="hello")
    events, fake, _ = chat(
        client,
        monkeypatch,
        USER_A,
        "q",
        call("analyze_document", document_id=theirs["id"], task="Read it."),
        "I can't find that document.",
    )
    [result] = named(events, "tool_result")
    assert result["ok"] is False and "No document matches" in result["summary"]
    assert "TOP SECRET" not in json.dumps(fake.calls)
