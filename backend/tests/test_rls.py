"""RLS cross-user test against the real hosted Supabase project.

Requires backend/.env with SUPABASE_URL, SUPABASE_ANON_KEY and
SUPABASE_SERVICE_ROLE_KEY, and supabase/migrations/0001_init.sql applied.
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
    a.table("user_vector_stores").insert({"user_id": a_id, "vector_store_id": "vs_a"}).execute()
    doc = a.table("documents").insert({"user_id": a_id, "filename": "a.txt"}).execute().data[0]

    # Select: B sees nothing of A's.
    assert b.table("threads").select("*").eq("id", thread["id"]).execute().data == []
    assert b.table("messages").select("*").eq("thread_id", thread["id"]).execute().data == []
    assert b.table("user_vector_stores").select("*").eq("user_id", a_id).execute().data == []
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
    assert _rejected(
        lambda: b.table("user_vector_stores")
        .insert({"user_id": a_id, "vector_store_id": "vs_x"})
        .execute()
    )

    # B can't write a message into A's thread, even with B's own user_id.
    thread = a.table("threads").insert({"user_id": a_id, "title": "A"}).execute().data[0]
    assert _rejected(
        lambda: b.table("messages")
        .insert({"thread_id": thread["id"], "user_id": b_id, "role": "user", "content": "x"})
        .execute()
    )


def test_anonymous_client_sees_nothing(users):
    from supabase import create_client

    anon = create_client(URL, ANON)
    for table in ("threads", "messages", "user_vector_stores", "documents"):
        assert anon.table(table).select("*").execute().data == []
