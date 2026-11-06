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


class FakeRepo:
    def __init__(self, store: FakeStore, user_id: str):
        self.store = store
        self.user_id = user_id
        self.match_calls: list[tuple] = []

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

    def add_message(self, thread_id, role, content, sources=None):
        row = {
            "id": str(uuid.uuid4()),
            "thread_id": thread_id,
            "user_id": self.user_id,
            "role": role,
            "content": content,
            "sources": sources,
            "created_at": _ts(),
        }
        self.store.messages.append(row)
        return row

    # documents
    def create_document(self, filename):
        row = {
            "id": str(uuid.uuid4()),
            "user_id": self.user_id,
            "filename": filename,
            "status": "processing",
            "error": None,
            "chunk_count": 0,
            "created_at": _ts(),
        }
        self.store.documents.append(row)
        return row

    def update_document(self, document_id, **fields):
        d = next(d for d in self._mine(self.store.documents) if d["id"] == document_id)
        d.update(fields)
        return d

    def list_documents(self):
        return sorted(self._mine(self.store.documents), key=lambda d: d["created_at"], reverse=True)

    def delete_document(self, document_id):
        d = next((d for d in self._mine(self.store.documents) if d["id"] == document_id), None)
        if not d:
            return False
        self.store.documents.remove(d)
        self.store.chunks = [c for c in self.store.chunks if c["document_id"] != document_id]
        return True

    def has_completed_documents(self):
        return any(d["status"] == "completed" for d in self._mine(self.store.documents))

    # chunks
    def insert_chunks(self, document_id, chunks, embeddings):
        for i, (content, emb) in enumerate(zip(chunks, embeddings, strict=True)):
            self.store.chunks.append(
                {
                    "document_id": document_id,
                    "user_id": self.user_id,
                    "chunk_index": i,
                    "content": content,
                    "embedding": emb,
                }
            )

    def match_chunks(self, embedding, top_k):
        self.match_calls.append((embedding, top_k))
        docs = {d["id"]: d for d in self._mine(self.store.documents) if d["status"] == "completed"}
        hits = [c for c in self._mine(self.store.chunks) if c["document_id"] in docs]
        return [
            {
                "id": str(uuid.uuid4()),
                "document_id": c["document_id"],
                "filename": docs[c["document_id"]]["filename"],
                "chunk_index": c["chunk_index"],
                "content": c["content"],
                "similarity": 0.9,
            }
            for c in hits[:top_k]
        ]


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
