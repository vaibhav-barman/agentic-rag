"""In-memory stand-ins for the Supabase repo and the LLM, shared by unit tests."""

import itertools
import uuid
from datetime import UTC, datetime, timedelta

from app.services import llm

_clock = itertools.count()


def _ts() -> str:
    # Strictly increasing timestamps so ordering is deterministic.
    return (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=next(_clock))).isoformat()


class FakeStore:
    """Rows for all users; each FakeRepo sees only its own (like RLS)."""

    def __init__(self):
        self.threads: list[dict] = []
        self.messages: list[dict] = []
        self.documents: list[dict] = []
        self.chunks: list[dict] = []
        self.contents: dict[str, str] = {}
        self.files: dict[str, bytes] = {}


class FakeRepo:
    def __init__(self, store: FakeStore, user_id: str):
        self.store = store
        self.user_id = user_id
        self.search_calls: list[dict] = []
        self.sql_calls: list[str] = []
        self.sql_result: list[dict] | Exception = []

    def _mine(self, rows):
        return [r for r in rows if r["user_id"] == self.user_id]

    # threads
    def create_thread(self, title=None):
        now = _ts()
        row = {
            "id": str(uuid.uuid4()),
            "user_id": self.user_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
        }
        self.store.threads.append(row)
        return row

    def list_threads(self):
        return sorted(self._mine(self.store.threads), key=lambda r: r["updated_at"], reverse=True)

    def get_thread(self, thread_id):
        return next((t for t in self._mine(self.store.threads) if t["id"] == thread_id), None)

    def update_thread(self, thread_id, **fields):
        fields.setdefault("updated_at", _ts())
        t = self.get_thread(thread_id)
        if t:
            t.update(fields)

    def delete_thread(self, thread_id):
        t = self.get_thread(thread_id)
        if not t:
            return False
        self.store.threads.remove(t)
        self.store.messages = [m for m in self.store.messages if m["thread_id"] != thread_id]
        return True

    # messages
    def list_messages(self, thread_id, limit=None):
        rows = [m for m in self._mine(self.store.messages) if m["thread_id"] == thread_id]
        rows.sort(key=lambda m: m["created_at"])
        return rows[-limit:] if limit is not None else rows

    def add_message(self, thread_id, role, content, sources=None, steps=None):
        row = {
            "id": str(uuid.uuid4()),
            "thread_id": thread_id,
            "user_id": self.user_id,
            "role": role,
            "content": content,
            "sources": sources,
            "steps": steps,
            "created_at": _ts(),
        }
        self.store.messages.append(row)
        return row

    # documents
    def create_document(self, filename, **fields):
        now = _ts()
        row = {
            "id": str(uuid.uuid4()),
            "user_id": self.user_id,
            "filename": filename,
            "status": "pending",
            "error": None,
            "chunk_count": 0,
            "file_size": None,
            "mime_type": None,
            "metadata": {},
            "ingest_stats": None,
            "content_hash": None,
            "storage_path": None,
            "created_at": now,
            "updated_at": now,
            **fields,
        }
        self.store.documents.append(row)
        return row

    def update_document(self, document_id, **fields):
        d = next(d for d in self._mine(self.store.documents) if d["id"] == document_id)
        d.update(fields)
        return d

    def get_document(self, document_id):
        return next((d for d in self._mine(self.store.documents) if d["id"] == document_id), None)

    def find_document_by_filename(self, filename):
        return next(
            (d for d in self._mine(self.store.documents) if d["filename"] == filename), None
        )

    def find_document_by_hash(self, content_hash):
        return next(
            (
                d
                for d in self._mine(self.store.documents)
                if d["content_hash"] == content_hash and d["status"] != "failed"
            ),
            None,
        )

    def list_documents(self):
        return sorted(self._mine(self.store.documents), key=lambda d: d["created_at"], reverse=True)

    def delete_document(self, document_id):
        d = self.get_document(document_id)
        if not d:
            return False
        self.store.documents.remove(d)
        self.store.chunks = [c for c in self.store.chunks if c["document_id"] != document_id]
        self.store.contents.pop(document_id, None)
        return True

    def has_completed_documents(self):
        return any(d["status"] == "completed" for d in self._mine(self.store.documents))

    def library_overview(self, limit=50):
        docs = [d for d in self.list_documents() if d["status"] == "completed"]
        return [
            {k: d[k] for k in ("id", "filename", "chunk_count", "metadata")} for d in docs[:limit]
        ]

    def set_document_content(self, document_id, content):
        self.store.contents[document_id] = content

    def get_document_content(self, document_id):
        return self.store.contents.get(document_id) if self.get_document(document_id) else None

    # storage
    def upload_file(self, path, data, mime_type):
        assert path.startswith(self.user_id + "/")
        self.store.files[path] = data

    def download_file(self, path):
        return self.store.files[path]

    def remove_file(self, path):
        self.store.files.pop(path, None)

    # chunks
    def _doc_chunks(self, document_id):
        rows = [c for c in self._mine(self.store.chunks) if c["document_id"] == document_id]
        return sorted(rows, key=lambda c: c["chunk_index"])

    def list_chunks(self, document_id):
        return [
            {k: c.get(k) for k in ("id", "chunk_index", "content_hash")}
            for c in self._doc_chunks(document_id)
        ]

    def get_chunks(self, document_id, start=0, end=None):
        return [
            {"chunk_index": c["chunk_index"], "content": c["content"]}
            for c in self._doc_chunks(document_id)
            if c["chunk_index"] >= start and (end is None or c["chunk_index"] <= end)
        ]

    def insert_chunks(self, document_id, chunks):
        for c in chunks:
            self.store.chunks.append(
                {
                    "id": str(uuid.uuid4()),
                    "document_id": document_id,
                    "user_id": self.user_id,
                    "content_hash": None,
                    **c,
                }
            )

    def update_chunk_index(self, chunk_id, chunk_index):
        next(c for c in self.store.chunks if c["id"] == chunk_id)["chunk_index"] = chunk_index

    def delete_chunks(self, chunk_ids):
        self.store.chunks = [c for c in self.store.chunks if c["id"] not in set(chunk_ids)]

    def search_chunks(
        self,
        query_text,
        embedding,
        *,
        match_count,
        mode="hybrid",
        metadata_filter=None,
        filename=None,
        document_id=None,
        min_similarity=0.0,
    ):
        """No real ranking: returns matching chunks in insertion order."""
        self.search_calls.append(
            {
                "query_text": query_text,
                "embedding": embedding,
                "match_count": match_count,
                "mode": mode,
                "metadata_filter": metadata_filter,
                "filename": filename,
                "document_id": document_id,
                "min_similarity": min_similarity,
            }
        )
        docs = {d["id"]: d for d in self._mine(self.store.documents) if d["status"] == "completed"}

        def matches(doc):
            for key, want in (metadata_filter or {}).items():
                have = doc["metadata"].get(key)
                if isinstance(want, list):
                    if not set(want) <= set(have or []):
                        return False
                elif have != want:
                    return False
            if filename and filename.lower() not in doc["filename"].lower():
                return False
            return not document_id or doc["id"] == document_id

        hits = [
            c
            for c in self._mine(self.store.chunks)
            if c["document_id"] in docs and matches(docs[c["document_id"]])
        ]
        return [
            {
                "id": c["id"],
                "document_id": c["document_id"],
                "filename": docs[c["document_id"]]["filename"],
                "chunk_index": c["chunk_index"],
                "content": c["content"],
                "similarity": 0.9,
                "vector_rank": i + 1,
                "keyword_rank": None,
                "score": round(1 / (60 + i + 1), 6),
            }
            for i, c in enumerate(hits[:match_count])
        ]

    # text-to-SQL
    def run_sql(self, query):
        self.sql_calls.append(query)
        if isinstance(self.sql_result, Exception):
            raise self.sql_result
        return self.sql_result


class ScriptedLLM:
    """Replaces llm.stream_chat: each call pops the next scripted reply.

    A reply is either a string (streamed as word deltas) or a list of ToolCall.
    Records the messages and tools of every call.
    """

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls: list[dict] = []

    async def stream_chat(self, messages, tools=None):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, list):
            yield llm.StreamEvent(type="tool_calls", tool_calls=reply)
            return
        for i, word in enumerate(reply.split(" ")):
            yield llm.StreamEvent(type="delta", text=word if i == 0 else " " + word)


async def fake_embed(texts):
    return [[float(len(t)), 1.0] for t in texts]


class ScriptedStructured:
    """Replaces llm.complete_structured: pops the next reply (a model instance,
    a dict to validate, or an Exception to raise)."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls: list[dict] = []

    async def complete_structured(self, messages, response_model):
        self.calls.append({"messages": messages, "response_model": response_model})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, dict):
            return response_model.model_validate(reply)
        return reply


async def no_structured(messages, response_model):
    raise RuntimeError("structured output not scripted")
