"""Data access, always as the calling user so Supabase RLS applies.

Routers depend on `get_repo`, which tests override with an in-memory fake.
"""

from datetime import UTC, datetime
from typing import Any, cast

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


DOCUMENT_COLUMNS = (
    "id,filename,status,error,chunk_count,file_size,mime_type,metadata,ingest_stats,"
    "content_hash,storage_path,created_at,updated_at"
)


def _rows(response: Any) -> list[dict]:
    """Typed view of a PostgREST response's `.data` (supabase-py types it as JSON)."""
    return cast("list[dict]", response.data)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Repo:
    def __init__(self, client: Client, user_id: str):
        self.db = client
        self.user_id = user_id

    # --- threads -----------------------------------------------------------
    def create_thread(self, title: str | None = None) -> dict:
        row = {"user_id": self.user_id, "title": title}
        return _rows(self.db.table("threads").insert(row).execute())[0]

    def list_threads(self) -> list[dict]:
        return _rows(
            self.db.table("threads")
            .select("id,title,created_at,updated_at")
            .order("updated_at", desc=True)
            .execute()
        )

    def get_thread(self, thread_id: str) -> dict | None:
        rows = _rows(self.db.table("threads").select("*").eq("id", thread_id).limit(1).execute())
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
            .select("id,role,content,sources,steps,created_at")
            .eq("thread_id", thread_id)
            .order("created_at", desc=limit is not None)
        )
        if limit is not None:
            query = query.limit(limit)
        rows = _rows(query.execute())
        return list(reversed(rows)) if limit is not None else rows

    def add_message(
        self,
        thread_id: str,
        role: str,
        content: str,
        sources: list[dict] | None = None,
        steps: list[dict] | None = None,
    ) -> dict:
        row = {
            "thread_id": thread_id,
            "user_id": self.user_id,
            "role": role,
            "content": content,
            "sources": sources,
            "steps": steps,
        }
        return _rows(self.db.table("messages").insert(row).execute())[0]

    # --- documents ---------------------------------------------------------
    def create_document(self, filename: str, **fields: Any) -> dict:
        row = {"user_id": self.user_id, "filename": filename, "status": "pending", **fields}
        return _rows(self.db.table("documents").insert(row).execute())[0]

    def update_document(self, document_id: str, **fields: Any) -> dict:
        fields.setdefault("updated_at", _now())
        return _rows(self.db.table("documents").update(fields).eq("id", document_id).execute())[0]

    def get_document(self, document_id: str) -> dict | None:
        rows = _rows(
            self.db.table("documents").select(DOCUMENT_COLUMNS).eq("id", document_id).execute()
        )
        return rows[0] if rows else None

    def find_document_by_filename(self, filename: str) -> dict | None:
        rows = _rows(
            self.db.table("documents").select(DOCUMENT_COLUMNS).eq("filename", filename).execute()
        )
        return rows[0] if rows else None

    def find_document_by_hash(self, content_hash: str) -> dict | None:
        rows = _rows(
            self.db.table("documents")
            .select(DOCUMENT_COLUMNS)
            .eq("content_hash", content_hash)
            .neq("status", "failed")
            .order("created_at")
            .limit(1)
            .execute()
        )
        return rows[0] if rows else None

    def list_documents(self) -> list[dict]:
        return _rows(
            self.db.table("documents")
            .select(DOCUMENT_COLUMNS)
            .order("created_at", desc=True)
            .execute()
        )

    def delete_document(self, document_id: str) -> bool:
        return bool(self.db.table("documents").delete().eq("id", document_id).execute().data)

    def has_completed_documents(self) -> bool:
        rows = (
            self.db.table("documents").select("id").eq("status", "completed").limit(1).execute()
        ).data
        return bool(rows)

    def library_overview(self, limit: int = 50) -> list[dict]:
        """Completed documents with their metadata, for the agent's system prompt."""
        return _rows(
            self.db.table("documents")
            .select("id,filename,chunk_count,metadata")
            .eq("status", "completed")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )

    # --- full document text (for the sub-agent) ------------------------------
    def set_document_content(self, document_id: str, content: str) -> None:
        row = {
            "document_id": document_id,
            "user_id": self.user_id,
            "content": content,
            "updated_at": _now(),
        }
        self.db.table("document_contents").upsert(row).execute()

    def get_document_content(self, document_id: str) -> str | None:
        rows = _rows(
            self.db.table("document_contents")
            .select("content")
            .eq("document_id", document_id)
            .execute()
        )
        return rows[0]["content"] if rows else None

    # --- file storage --------------------------------------------------------
    def _bucket(self):
        return self.db.storage.from_(get_settings().storage_bucket)

    def upload_file(self, path: str, data: bytes, mime_type: str) -> None:
        self._bucket().upload(path, data, {"content-type": mime_type, "upsert": "true"})

    def download_file(self, path: str) -> bytes:
        return self._bucket().download(path)

    def remove_file(self, path: str) -> None:
        self._bucket().remove([path])

    # --- chunks / retrieval ------------------------------------------------
    def list_chunks(self, document_id: str) -> list[dict]:
        """Chunk ids, positions and hashes (no text, no vectors), in order."""
        return _rows(
            self.db.table("document_chunks")
            .select("id,chunk_index,content_hash")
            .eq("document_id", document_id)
            .order("chunk_index")
            .execute()
        )

    def get_chunks(self, document_id: str, start: int = 0, end: int | None = None) -> list[dict]:
        """Chunk text for positions start..end (inclusive), in order."""
        query = (
            self.db.table("document_chunks")
            .select("chunk_index,content")
            .eq("document_id", document_id)
            .gte("chunk_index", start)
            .order("chunk_index")
        )
        if end is not None:
            query = query.lte("chunk_index", end)
        return _rows(query.execute())

    def insert_chunks(self, document_id: str, chunks: list[dict]) -> None:
        """Each chunk: {chunk_index, content, content_hash, embedding}."""
        rows = [{"document_id": document_id, "user_id": self.user_id, **c} for c in chunks]
        for start in range(0, len(rows), 100):
            self.db.table("document_chunks").insert(rows[start : start + 100]).execute()

    def update_chunk_index(self, chunk_id: str, chunk_index: int) -> None:
        self.db.table("document_chunks").update({"chunk_index": chunk_index}).eq(
            "id", chunk_id
        ).execute()

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        for start in range(0, len(chunk_ids), 100):
            self.db.table("document_chunks").delete().in_(
                "id", chunk_ids[start : start + 100]
            ).execute()

    def search_chunks(
        self,
        query_text: str,
        embedding: list[float],
        *,
        match_count: int,
        mode: str = "hybrid",
        metadata_filter: dict | None = None,
        filename: str | None = None,
        document_id: str | None = None,
        min_similarity: float = 0.0,
    ) -> list[dict]:
        """Candidate chunks from the caller's completed documents, best first."""
        params: dict[str, Any] = {
            "query_embedding": embedding,
            "match_count": match_count,
            "filter": metadata_filter or {},
            "filename_filter": filename,
            "document_id_filter": document_id,
        }
        if mode == "vector":
            params["match_threshold"] = min_similarity
            return _rows(self.db.rpc("match_document_chunks", params).execute())
        params.update({"query_text": query_text, "search_mode": mode})
        return _rows(self.db.rpc("hybrid_search_chunks", params).execute())

    # --- text-to-SQL ---------------------------------------------------------
    def run_sql(self, query: str) -> list[dict]:
        """Run a read-only SELECT as the user (RLS applies). Raises on rejection."""
        return _rows(self.db.rpc("execute_readonly_sql", {"query": query}).execute())


def get_repo(user: CurrentUser = Depends(get_current_user)) -> Repo:
    return Repo(user_client(user), user.id)
