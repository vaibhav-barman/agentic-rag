"""RLS cross-user test against the real hosted Supabase project.

Requires backend/.env with SUPABASE_URL, SUPABASE_ANON_KEY and
SUPABASE_SERVICE_ROLE_KEY, and every file in supabase/migrations applied
(venv/bin/python scripts/apply_migrations.py).
Creates two throwaway users and deletes them afterwards (rows cascade).

Run: venv/bin/pytest -m integration tests/test_rls.py -v
"""

import uuid
from pathlib import Path

import pytest
from dotenv import dotenv_values

ENV = dotenv_values(Path(__file__).resolve().parent.parent / ".env")
URL = ENV.get("SUPABASE_URL") or ""
ANON = ENV.get("SUPABASE_ANON_KEY") or ""
SERVICE = ENV.get("SUPABASE_SERVICE_ROLE_KEY") or ""

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (URL and ANON and SERVICE) or "your-project-ref" in URL,
        reason="backend/.env with real Supabase credentials not present",
    ),
]

PASSWORD = "Rls-test-" + uuid.uuid4().hex


@pytest.fixture(scope="module")
def users():
    from supabase import create_client
    from supabase_auth.errors import AuthApiError  # noqa: F401  (import check)

    admin = create_client(URL, SERVICE)
    created = []
    clients = []
    try:
        for label in ("a", "b"):
            email = f"rls-{label}-{uuid.uuid4().hex[:8]}@example.com"
            res = admin.auth.admin.create_user(
                {"email": email, "password": PASSWORD, "email_confirm": True}
            )
            created.append(res.user.id)
            client = create_client(URL, ANON)
            client.auth.sign_in_with_password({"email": email, "password": PASSWORD})
            clients.append((res.user.id, client))
        yield clients
    finally:
        for uid in created:
            admin.auth.admin.delete_user(uid)


def _rejected(fn) -> bool:
    from postgrest.exceptions import APIError

    try:
        fn()
    except APIError:
        return True
    return False


def test_user_b_cannot_see_or_modify_user_a_rows(users):
    (a_id, a), (b_id, b) = users

    thread = a.table("threads").insert({"user_id": a_id, "title": "A secret"}).execute().data[0]
    a.table("messages").insert(
        {"thread_id": thread["id"], "user_id": a_id, "role": "user", "content": "hi"}
    ).execute()
    doc = a.table("documents").insert({"user_id": a_id, "filename": "a.txt"}).execute().data[0]

    # Select: B sees nothing of A's.
    assert b.table("threads").select("*").eq("id", thread["id"]).execute().data == []
    assert b.table("messages").select("*").eq("thread_id", thread["id"]).execute().data == []
    assert b.table("documents").select("*").eq("id", doc["id"]).execute().data == []

    # Update / delete: B affects zero rows; A's data is untouched.
    assert b.table("threads").update({"title": "pwned"}).eq("id", thread["id"]).execute().data == []
    assert b.table("documents").delete().eq("id", doc["id"]).execute().data == []
    assert a.table("threads").select("title").eq("id", thread["id"]).execute().data == [
        {"title": "A secret"}
    ]
    assert len(a.table("documents").select("id").eq("id", doc["id"]).execute().data) == 1


def test_inserts_with_foreign_user_id_are_rejected(users):
    (a_id, a), (b_id, b) = users

    assert _rejected(lambda: b.table("threads").insert({"user_id": a_id, "title": "x"}).execute())
    assert _rejected(
        lambda: b.table("documents").insert({"user_id": a_id, "filename": "x.txt"}).execute()
    )

    # B can't write a message into A's thread, even with B's own user_id.
    thread = a.table("threads").insert({"user_id": a_id, "title": "A"}).execute().data[0]
    assert _rejected(
        lambda: (
            b.table("messages")
            .insert({"thread_id": thread["id"], "user_id": b_id, "role": "user", "content": "x"})
            .execute()
        )
    )


def test_anonymous_client_sees_nothing(users):
    from supabase import create_client

    anon = create_client(URL, ANON)
    for table in ("threads", "messages", "documents", "document_chunks", "document_contents"):
        assert anon.table(table).select("*").execute().data == []


DIMS = 1024


def _vec(hot: int) -> list[float]:
    v = [0.0] * DIMS
    v[hot] = 1.0
    return v


def test_chunks_and_match_function_are_isolated(users):
    (a_id, a), (b_id, b) = users

    doc = (
        a.table("documents")
        .insert({"user_id": a_id, "filename": "a-secret.txt", "status": "completed"})
        .execute()
        .data[0]
    )
    a.table("document_chunks").insert(
        {
            "document_id": doc["id"],
            "user_id": a_id,
            "chunk_index": 0,
            "content": "A's secret fact",
            "embedding": _vec(0),
        }
    ).execute()

    # A finds its own chunk through the RPC.
    hits = (
        a.rpc("match_document_chunks", {"query_embedding": _vec(0), "match_count": 5})
        .execute()
        .data
    )
    assert [h["content"] for h in hits] == ["A's secret fact"]
    assert hits[0]["filename"] == "a-secret.txt" and hits[0]["similarity"] > 0.99

    # B sees nothing, directly or through the RPC.
    assert b.table("document_chunks").select("*").execute().data == []
    assert (
        b.rpc("match_document_chunks", {"query_embedding": _vec(0), "match_count": 5})
        .execute()
        .data
        == []
    )

    # B can't attach chunks to A's document.
    assert _rejected(
        lambda: (
            b.table("document_chunks")
            .insert(
                {
                    "document_id": doc["id"],
                    "user_id": b_id,
                    "chunk_index": 1,
                    "content": "x",
                    "embedding": _vec(1),
                }
            )
            .execute()
        )
    )

    # Deleting the document cascades to its chunks.
    a.table("documents").delete().eq("id", doc["id"]).execute()
    assert a.table("document_chunks").select("id").execute().data == []


# --- Modules 2-8: storage, record manager, metadata, hybrid search, SQL, contents ----


def _doc_with_chunk(client, user_id, filename, content, hot, metadata=None):
    doc = (
        client.table("documents")
        .insert(
            {
                "user_id": user_id,
                "filename": filename,
                "status": "completed",
                "metadata": metadata or {},
            }
        )
        .execute()
        .data[0]
    )
    client.table("document_chunks").insert(
        {
            "document_id": doc["id"],
            "user_id": user_id,
            "chunk_index": 0,
            "content": content,
            "content_hash": "h",
            "embedding": _vec(hot),
        }
    ).execute()
    return doc


def test_option_a_cleanup_removed_the_managed_rag_schema(users):
    (_, a), _ = users
    assert _rejected(lambda: a.table("user_vector_stores").select("*").execute())
    assert _rejected(lambda: a.table("threads").select("last_response_id").execute())
    assert _rejected(lambda: a.table("documents").select("openai_file_id").execute())


def test_storage_objects_are_private_to_their_owner(users):
    (a_id, a), (b_id, b) = users
    path = f"{a_id}/{uuid.uuid4()}/original.txt"
    a.storage.from_("documents").upload(path, b"A's file", {"content-type": "text/plain"})
    assert a.storage.from_("documents").download(path) == b"A's file"

    # B can neither read A's object nor write into A's folder.
    with pytest.raises(Exception):  # noqa: B017  (storage3 raises its own error type)
        b.storage.from_("documents").download(path)
    with pytest.raises(Exception):  # noqa: B017
        b.storage.from_("documents").upload(
            f"{a_id}/{uuid.uuid4()}/original.txt", b"x", {"content-type": "text/plain"}
        )
    assert b.storage.from_("documents").list(a_id) == []

    a.storage.from_("documents").remove([path])
    with pytest.raises(Exception):  # noqa: B017
        a.storage.from_("documents").download(path)


def test_filename_is_unique_per_user_not_globally(users):
    (a_id, a), (b_id, b) = users
    name = f"same-{uuid.uuid4().hex[:6]}.txt"
    first = a.table("documents").insert({"user_id": a_id, "filename": name}).execute().data[0]
    assert first["status"] == "pending"  # new default
    assert _rejected(
        lambda: a.table("documents").insert({"user_id": a_id, "filename": name}).execute()
    )
    b.table("documents").insert({"user_id": b_id, "filename": name}).execute()


def test_hybrid_search_keyword_leg_filters_and_isolation(users):
    (a_id, a), (b_id, b) = users
    tag = uuid.uuid4().hex[:6]
    report = _doc_with_chunk(
        a,
        a_id,
        f"report-{tag}.md",
        "The warranty reference is XK-7741-Q for the turbine.",
        hot=10,
        metadata={"document_type": "report", "topics": ["warranty"]},
    )
    notes = _doc_with_chunk(
        a, a_id, f"notes-{tag}.md", "Buy oat milk.", hot=11, metadata={"document_type": "notes"}
    )

    def search(client, **params):
        base = {"query_text": "XK-7741-Q", "query_embedding": _vec(11), "match_count": 10}
        rows = client.rpc("hybrid_search_chunks", {**base, **params}).execute().data
        return [r for r in rows if r["document_id"] in {report["id"], notes["id"]}]

    # The query vector points at the notes chunk, but the exact code is only in the
    # report: the keyword leg finds it, and RRF puts it in the results.
    hybrid = search(a)
    by_doc = {r["document_id"]: r for r in hybrid}
    assert by_doc[report["id"]]["keyword_rank"] == 1
    assert by_doc[notes["id"]]["keyword_rank"] is None and by_doc[notes["id"]]["vector_rank"]
    assert all(r["score"] > 0 for r in hybrid)

    assert [r["document_id"] for r in search(a, search_mode="keyword")] == [report["id"]]
    vector_only = search(a, search_mode="vector")
    assert vector_only[0]["document_id"] == notes["id"]
    assert all(r["keyword_rank"] is None for r in vector_only)

    # Metadata filter (Module 4), filename filter and single-document scope (Module 8).
    assert {r["document_id"] for r in search(a, filter={"document_type": "notes"})} == {notes["id"]}
    assert {r["document_id"] for r in search(a, filter={"topics": ["warranty"]})} == {report["id"]}
    assert {r["document_id"] for r in search(a, filename_filter=f"REPORT-{tag}")} == {report["id"]}
    assert {r["document_id"] for r in search(a, document_id_filter=notes["id"])} == {notes["id"]}

    # The vector RPC takes the same filters plus a similarity threshold.
    matched = (
        a.rpc(
            "match_document_chunks",
            {
                "query_embedding": _vec(11),
                "match_count": 10,
                "match_threshold": 0.5,
                "filter": {"document_type": "notes"},
            },
        )
        .execute()
        .data
    )
    assert [m["document_id"] for m in matched] == [notes["id"]]

    # RLS: B gets nothing from either function.
    assert search(b) == []


def test_readonly_sql_is_scoped_by_rls_and_refuses_writes(users):
    (a_id, a), (b_id, b) = users
    name = f"sql-{uuid.uuid4().hex[:6]}.txt"
    a.table("documents").insert({"user_id": a_id, "filename": name}).execute()

    def run(client, query):
        return client.rpc("execute_readonly_sql", {"query": query}).execute().data

    mine = run(a, f"select filename from documents where filename = '{name}'")
    assert mine == [{"filename": name}]
    assert run(b, f"select filename from documents where filename = '{name}'") == []
    # B's total never includes A's rows.
    assert run(b, "select count(*) as n from documents where user_id <> auth.uid()") == [{"n": 0}]

    for bad in (
        f"delete from documents where filename = '{name}'",
        f"with gone as (delete from documents where filename = '{name}' returning 1) "
        "select * from gone",
        "select 1; select 2",
        "select * from auth.users",
        "select pg_sleep(1)",
        "select set_config('role', 'postgres', true)",
    ):
        assert _rejected(lambda q=bad: run(a, q)), bad
    assert len(a.table("documents").select("id").eq("filename", name).execute().data) == 1

    from supabase import create_client

    anon = create_client(URL, ANON)
    assert _rejected(lambda: run(anon, "select 1"))


def test_document_contents_are_private_and_cascade(users):
    (a_id, a), (b_id, b) = users
    doc = _doc_with_chunk(a, a_id, f"full-{uuid.uuid4().hex[:6]}.md", "chunk", hot=20)
    a.table("document_contents").insert(
        {"document_id": doc["id"], "user_id": a_id, "content": "the whole text"}
    ).execute()

    assert (
        b.table("document_contents").select("*").eq("document_id", doc["id"]).execute().data == []
    )
    assert _rejected(
        lambda: (
            b.table("document_contents")
            .insert({"document_id": doc["id"], "user_id": b_id, "content": "x"})
            .execute()
        )
    )

    # Module 5: deleting the document removes its chunks and stored text.
    a.table("documents").delete().eq("id", doc["id"]).execute()
    assert (
        a.table("document_contents").select("*").eq("document_id", doc["id"]).execute().data == []
    )
    assert a.table("document_chunks").select("id").eq("document_id", doc["id"]).execute().data == []
