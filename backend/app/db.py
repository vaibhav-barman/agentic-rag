"""Data access, always as the calling user so Supabase RLS applies.

Routers depend on `get_repo`, which tests override with an in-memory fake.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import Depends
from supabase import Client, ClientOptions, create_client

from app.auth import get_current_user
from app.config import get_settings
from app.schemas import CurrentUser


def user_client(user: CurrentUser) -> Client:
    """Supabase client that sends the user's JWT, so every query runs under RLS."""
    settings = get_settings()
    return create_client(
        settings.supabase_url,
        settings.supabase_anon_key,
        options=ClientOptions(
            headers={"Authorization": f"Bearer {user.access_token}"},
            auto_refresh_token=False,
            persist_session=False,
        ),
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Repo:
    def __init__(self, client: Client, user_id: str):
        self.db = client
        self.user_id = user_id

    # --- threads -----------------------------------------------------------
    def create_thread(self, title: str | None = None) -> dict:
        row = {"user_id": self.user_id, "title": title}
        return self.db.table("threads").insert(row).execute().data[0]

    def list_threads(self) -> list[dict]:
        return (
            self.db.table("threads")
            .select("id,title,created_at,updated_at")
            .order("updated_at", desc=True)
            .execute()
            .data
        )

    def get_thread(self, thread_id: str) -> dict | None:
        rows = self.db.table("threads").select("*").eq("id", thread_id).limit(1).execute().data
        return rows[0] if rows else None

    def update_thread(self, thread_id: str, **fields: Any) -> None:
        fields.setdefault("updated_at", _now())
        self.db.table("threads").update(fields).eq("id", thread_id).execute()

    def delete_thread(self, thread_id: str) -> bool:
        return bool(self.db.table("threads").delete().eq("id", thread_id).execute().data)

    # --- messages ----------------------------------------------------------
    def list_messages(self, thread_id: str, limit: int | None = None) -> list[dict]:
        """Oldest-first. With `limit`, the most recent `limit` messages."""
        query = (
            self.db.table("messages")
            .select("id,role,content,sources,created_at")
            .eq("thread_id", thread_id)
            .order("created_at", desc=limit is not None)
        )
        if limit is not None:
            query = query.limit(limit)
        rows = query.execute().data
        return list(reversed(rows)) if limit is not None else rows

    def add_message(
        self, thread_id: str, role: str, content: str, sources: list[dict] | None = None
    ) -> dict:
        row = {
            "thread_id": thread_id,
            "user_id": self.user_id,
            "role": role,
            "content": content,
            "sources": sources,
        }
        return self.db.table("messages").insert(row).execute().data[0]

    # --- documents ---------------------------------------------------------
    def create_document(self, filename: str) -> dict:
        row = {"user_id": self.user_id, "filename": filename, "status": "processing"}
        return self.db.table("documents").insert(row).execute().data[0]

    def update_document(self, document_id: str, **fields: Any) -> dict:
        return (
            self.db.table("documents").update(fields).eq("id", document_id).execute().data[0]
        )

    def list_documents(self) -> list[dict]:
        return (
            self.db.table("documents")
            .select("id,filename,status,error,chunk_count,created_at")
            .order("created_at", desc=True)
            .execute()
            .data
        )

    def delete_document(self, document_id: str) -> bool:
        return bool(self.db.table("documents").delete().eq("id", document_id).execute().data)

    def has_completed_documents(self) -> bool:
        rows = (
            self.db.table("documents").select("id").eq("status", "completed").limit(1).execute()
        ).data
        return bool(rows)

    # --- chunks / retrieval ------------------------------------------------
    def insert_chunks(self, document_id: str, chunks: list[str], embeddings: list[list[float]]):
        rows = [
            {
                "document_id": document_id,
                "user_id": self.user_id,
                "chunk_index": i,
                "content": content,
                "embedding": embedding,
            }
            for i, (content, embedding) in enumerate(zip(chunks, embeddings, strict=True))
        ]
        for start in range(0, len(rows), 100):
            self.db.table("document_chunks").insert(rows[start : start + 100]).execute()

    def match_chunks(self, embedding: list[float], top_k: int) -> list[dict]:
        return (
            self.db.rpc(
                "match_document_chunks", {"query_embedding": embedding, "match_count": top_k}
            )
            .execute()
            .data
        )


def get_repo(user: CurrentUser = Depends(get_current_user)) -> Repo:
    return Repo(user_client(user), user.id)
