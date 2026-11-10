"""Record manager: decide what an upload needs, so nothing is processed twice.

Two levels of content hashing:
- the whole file (documents.content_hash): is this upload new, changed, or already here?
- each chunk (document_chunks.content_hash): when a file changed, which chunks are
  really new? Only those are embedded; unchanged ones are kept, vanished ones deleted.
"""

import hashlib
from collections import defaultdict, deque
from dataclasses import dataclass, field


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def decide(repo, filename: str, content_hash: str) -> tuple[str, dict | None]:
    """Return (action, existing document).

    unchanged  same filename, same bytes, already ingested (or in progress): skip
    updated    same filename, different bytes (or a failed earlier attempt): re-ingest
    duplicate  same bytes under another filename: skip, point at the existing document
    created    never seen: ingest
    """
    same_name = repo.find_document_by_filename(filename)
    if same_name is not None:
        if same_name.get("content_hash") == content_hash and same_name["status"] != "failed":
            return "unchanged", same_name
        return "updated", same_name
    same_bytes = repo.find_document_by_hash(content_hash)
    if same_bytes is not None:
        return "duplicate", same_bytes
    return "created", None


@dataclass
class ChunkPlan:
    """What to do with a document's chunks, given the new chunk hashes."""

    to_embed: list[int] = field(default_factory=list)  # positions of new chunks
    to_move: list[tuple[str, int]] = field(default_factory=list)  # (chunk id, new position)
    to_delete: list[str] = field(default_factory=list)  # chunk ids no longer present
    reused: int = 0

    @property
    def stats(self) -> dict:
        return {
            "embedded": len(self.to_embed),
            "reused": self.reused,
            "removed": len(self.to_delete),
        }


def plan_chunks(existing: list[dict], new_hashes: list[str]) -> ChunkPlan:
    """Match new chunks to stored ones by hash. `existing`: {id, chunk_index, content_hash}."""
    pool: dict[str, deque[dict]] = defaultdict(deque)
    for row in existing:
        if row.get("content_hash"):
            pool[row["content_hash"]].append(row)

    plan = ChunkPlan()
    kept: set[str] = set()
    for position, chunk_hash in enumerate(new_hashes):
        if pool[chunk_hash]:
            row = pool[chunk_hash].popleft()
            kept.add(row["id"])
            plan.reused += 1
            if row["chunk_index"] != position:
                plan.to_move.append((row["id"], position))
        else:
            plan.to_embed.append(position)
    plan.to_delete = [row["id"] for row in existing if row["id"] not in kept]
    return plan
