import json
import time
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import get_repo
from app.main import app
from app.services import chat as chat_service
from app.services import llm
from tests.fakes import FakeRepo, FakeStore, ScriptedLLM, fake_embed

settings = get_settings()
USER_A = str(uuid.uuid4())
USER_B = str(uuid.uuid4())


def token_for(user_id: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": user_id,
            "email": f"{user_id[:4]}@x.com",
            "aud": "authenticated",
            "iat": now,
            "exp": now + 3600,
        },
        settings.supabase_jwt_secret,
        algorithm="HS256",
    )


@pytest.fixture
def store():
    return FakeStore()


@pytest.fixture
def client(store):
    from app.auth import get_current_user

    def repo_override(user=pytest.importorskip("fastapi").Depends(get_current_user)):
        return FakeRepo(store, user.id)

    app.dependency_overrides[get_repo] = repo_override
    yield TestClient(app)
    app.dependency_overrides.clear()


def h(user_id):
    return {"Authorization": f"Bearer {token_for(user_id)}"}


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


# --- B.3 thread endpoints -------------------------------------------------


def test_threads_require_auth(client):
    assert client.get("/threads").status_code == 401


def test_create_list_fetch_delete_thread(client):
    r = client.post("/threads", headers=h(USER_A), json={})
    assert r.status_code == 201
    tid = r.json()["id"]
    assert [t["id"] for t in client.get("/threads", headers=h(USER_A)).json()] == [tid]
    assert client.get(f"/threads/{tid}/messages", headers=h(USER_A)).json() == []
    assert client.delete(f"/threads/{tid}", headers=h(USER_A)).status_code == 204
    assert client.get("/threads", headers=h(USER_A)).json() == []


def test_threads_listed_newest_activity_first(client):
    t1 = client.post("/threads", headers=h(USER_A), json={}).json()["id"]
    t2 = client.post("/threads", headers=h(USER_A), json={}).json()["id"]
    assert [t["id"] for t in client.get("/threads", headers=h(USER_A)).json()] == [t2, t1]


def test_other_users_thread_is_404(client):
    tid = client.post("/threads", headers=h(USER_A), json={}).json()["id"]
    assert client.get("/threads", headers=h(USER_B)).json() == []
    assert client.get(f"/threads/{tid}/messages", headers=h(USER_B)).status_code == 404
    assert client.delete(f"/threads/{tid}", headers=h(USER_B)).status_code == 404
    assert (
        client.post(f"/threads/{tid}/chat", headers=h(USER_B), json={"content": "hi"}).status_code
        == 404
    )


# --- B.4 chat endpoint ----------------------------------------------------


def test_chat_streams_deltas_then_done_and_persists(client, monkeypatch):
    fake = ScriptedLLM("Hello there friend")
    monkeypatch.setattr(llm, "stream_chat", fake.stream_chat)
    tid = client.post("/threads", headers=h(USER_A), json={}).json()["id"]

    r = client.post(f"/threads/{tid}/chat", headers=h(USER_A), json={"content": "Hi, I am Ada"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    names = [e for e, _ in events]
    assert names[0] == "user_message"
    assert names[-1] == "done"
    assert "".join(d["text"] for e, d in events if e == "delta") == "Hello there friend"
    assert events[-1][1]["title"] == "Hi, I am Ada"

    msgs = client.get(f"/threads/{tid}/messages", headers=h(USER_A)).json()
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "Hi, I am Ada"),
        ("assistant", "Hello there friend"),
    ]
    assert client.get("/threads", headers=h(USER_A)).json()[0]["title"] == "Hi, I am Ada"


def test_chat_sends_history_for_memory(client, monkeypatch):
    fake = ScriptedLLM("Nice to meet you, Ada", "Your name is Ada")
    monkeypatch.setattr(llm, "stream_chat", fake.stream_chat)
    tid = client.post("/threads", headers=h(USER_A), json={}).json()["id"]
    client.post(f"/threads/{tid}/chat", headers=h(USER_A), json={"content": "My name is Ada"})
    client.post(f"/threads/{tid}/chat", headers=h(USER_A), json={"content": "What's my name?"})

    second = fake.calls[1]["messages"]
    assert second[0]["role"] == "system"
    assert [(m["role"], m["content"]) for m in second[1:]] == [
        ("user", "My name is Ada"),
        ("assistant", "Nice to meet you, Ada"),
        ("user", "What's my name?"),
    ]
    # Title stays from the first message.
    assert client.get("/threads", headers=h(USER_A)).json()[0]["title"] == "My name is Ada"


def test_history_window_is_limited(client, monkeypatch):
    monkeypatch.setattr(settings, "chat_history_limit", 3)
    fake = ScriptedLLM("a1", "a2", "a3")
    monkeypatch.setattr(llm, "stream_chat", fake.stream_chat)
    tid = client.post("/threads", headers=h(USER_A), json={}).json()["id"]
    for q in ("q1", "q2", "q3"):
        client.post(f"/threads/{tid}/chat", headers=h(USER_A), json={"content": q})
    assert [m["content"] for m in fake.calls[2]["messages"][1:]] == ["a1", "q2", "a2", "q3"][-3:]


def test_no_file_search_tool_without_documents(client, monkeypatch):
    fake = ScriptedLLM("ok")
    monkeypatch.setattr(llm, "stream_chat", fake.stream_chat)
    tid = client.post("/threads", headers=h(USER_A), json={}).json()["id"]
    client.post(f"/threads/{tid}/chat", headers=h(USER_A), json={"content": "hi"})
    assert fake.calls[0]["tools"] is None


def test_llm_failure_emits_error_event(client, monkeypatch):
    fake = ScriptedLLM(RuntimeError("rate limited"))
    monkeypatch.setattr(llm, "stream_chat", fake.stream_chat)
    tid = client.post("/threads", headers=h(USER_A), json={}).json()["id"]
    events = parse_sse(
        client.post(f"/threads/{tid}/chat", headers=h(USER_A), json={"content": "hi"}).text
    )
    assert ("error" in [e for e, _ in events]) and "rate limited" in events[-1][1]["message"]
    # Only the user message is stored.
    msgs = client.get(f"/threads/{tid}/messages", headers=h(USER_A)).json()
    assert [m["role"] for m in msgs] == ["user"]


def test_empty_message_rejected(client):
    tid = client.post("/threads", headers=h(USER_A), json={}).json()["id"]
    assert (
        client.post(f"/threads/{tid}/chat", headers=h(USER_A), json={"content": ""}).status_code
        == 422
    )


# --- C.3 file_search tool -------------------------------------------------


def test_file_search_tool_round_trip(client, store, monkeypatch):
    monkeypatch.setattr(llm, "embed", fake_embed)
    repo = FakeRepo(store, USER_A)
    doc = repo.create_document("facts.txt")
    repo.insert_chunks(doc["id"], ["The codename is BLUE HERON."], [[1.0, 1.0]])
    repo.update_document(doc["id"], status="completed")

    fake = ScriptedLLM(
        [
            llm.ToolCall(
                id="call_1",
                name="file_search",
                arguments='{"query": "codename"}',
                extra_content={"google": {"thought_signature": "sig"}},
            )
        ],
        "The codename is BLUE HERON (facts.txt).",
    )
    monkeypatch.setattr(llm, "stream_chat", fake.stream_chat)
    tid = client.post("/threads", headers=h(USER_A), json={}).json()["id"]
    events = parse_sse(
        client.post(
            f"/threads/{tid}/chat", headers=h(USER_A), json={"content": "What is the codename?"}
        ).text
    )

    assert fake.calls[0]["tools"] == [chat_service.FILE_SEARCH_TOOL]
    second = fake.calls[1]["messages"]
    assert second[-2]["tool_calls"][0]["function"]["name"] == "file_search"
    assert second[-2]["tool_calls"][0]["extra_content"] == {"google": {"thought_signature": "sig"}}
    assert second[-1]["role"] == "tool" and second[-1]["tool_call_id"] == "call_1"
    assert "BLUE HERON" in second[-1]["content"] and "facts.txt" in second[-1]["content"]

    sources = [d for e, d in events if e == "sources"]
    assert sources and sources[0]["query"] == "codename"
    assert sources[0]["sources"][0]["filename"] == "facts.txt"

    msgs = client.get(f"/threads/{tid}/messages", headers=h(USER_A)).json()
    assert msgs[-1]["sources"][0]["filename"] == "facts.txt"


def test_tool_rounds_are_capped(client, store, monkeypatch):
    monkeypatch.setattr(llm, "embed", fake_embed)
    monkeypatch.setattr(settings, "max_tool_rounds", 1)
    repo = FakeRepo(store, USER_A)
    doc = repo.create_document("a.txt")
    repo.update_document(doc["id"], status="completed")
    call = [llm.ToolCall(id="c", name="file_search", arguments='{"query":"x"}')]
    fake = ScriptedLLM(call, "final answer")
    monkeypatch.setattr(llm, "stream_chat", fake.stream_chat)
    tid = client.post("/threads", headers=h(USER_A), json={}).json()["id"]
    events = parse_sse(
        client.post(f"/threads/{tid}/chat", headers=h(USER_A), json={"content": "q"}).text
    )
    assert fake.calls[1]["tools"] is None  # last round must answer
    assert events[-1][0] == "done"


def test_trace_inputs_exclude_repo_and_token():
    from app.services.chat import _trace_inputs

    out = _trace_inputs(
        {"repo": object(), "thread": {"id": "t1", "title": None}, "user_content": "hi"}
    )
    assert out == {"thread_id": "t1", "user_content": "hi"}


def test_stream_chat_handles_tool_calls_without_index(monkeypatch):
    """Gemini streams tool calls with index=None; must parse (and not crash tracing)."""
    import asyncio
    from types import SimpleNamespace as NS

    chunks = [
        NS(
            usage=None,
            choices=[
                NS(
                    delta=NS(
                        content=None,
                        tool_calls=[
                            NS(
                                index=None,
                                id="call_9",
                                function=NS(name="file_search", arguments='{"query":"x"}'),
                                model_extra={
                                    "extra_content": {"google": {"thought_signature": "sig"}}
                                },
                            )
                        ],
                    )
                )
            ],
        ),
        NS(usage=NS(prompt_tokens=5, completion_tokens=3, total_tokens=8), choices=[]),
    ]

    async def fake_stream():
        for c in chunks:
            yield c

    class FakeCompletions:
        async def create(self, **kwargs):
            return fake_stream()

    fake_client = NS(chat=NS(completions=FakeCompletions()))
    monkeypatch.setattr(llm, "get_client", lambda: fake_client)

    async def collect():
        return [e async for e in llm.stream_chat([{"role": "user", "content": "q"}], [{}])]

    events = asyncio.run(collect())
    [calls] = [e for e in events if e.type == "tool_calls"]
    assert [(c.id, c.name, c.arguments) for c in calls.tool_calls] == [
        ("call_9", "file_search", '{"query":"x"}')
    ]
    assert calls.tool_calls[0].extra_content == {"google": {"thought_signature": "sig"}}
    assert events[-1].usage == {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8}
    out = llm._reduce_stream(events)
    assert out["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "file_search"
    assert out["usage_metadata"]["total_tokens"] == 8
