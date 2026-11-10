"""Ingestion pipeline, run in the background after an upload:

download from Storage -> parse -> chunk -> diff against stored chunks ->
embed what is new -> extract metadata -> mark the document completed.

Every status change is a row update, which Supabase Realtime pushes to the browser.
"""

import asyncio

from app.config import get_settings
from app.services import llm
from app.services.metadata import extract_metadata
from app.services.parsing import (  # noqa: F401  (re-exported for routers and tests)
    ALLOWED_EXTENSIONS,
    IngestionError,
    extension_of,
    mime_type_of,
    parse_document,
)
from app.services.record_manager import plan_chunks, sha256_hex


def chunk_text(text: str, size: int | None = None, overlap: int | None = None) -> list[str]:
    """Split into ~`size`-char chunks with `overlap` chars shared between neighbours.

    Breaks at the last Markdown heading, paragraph, sentence or word boundary inside
    the window when one exists in its second half, so chunks rarely cut words in two
    and tend to start where a section starts.
    """
    settings = get_settings()
    size = size or settings.chunk_size_chars
    overlap = settings.chunk_overlap_chars if overlap is None else overlap
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")

    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start:end]
            # (separator, how much of it stays at the end of this chunk)
            for sep, keep in (("\n#", 1), ("\n\n", 2), (". ", 2), ("\n", 1), (" ", 1)):
                cut = window.rfind(sep)
                if cut > size // 2:
                    end = start + cut + keep
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        next_start = max(end - overlap, start + 1)
        # Snap the overlap start forward to a word boundary so chunks don't begin mid-word.
        if not text[next_start - 1].isspace():
            space = text.find(" ", next_start, end)
            if space != -1:
                next_start = space + 1
        start = next_start
    return chunks


async def process_document(repo, document: dict) -> dict:
    """Ingest one stored file; returns the updated document row. Never raises."""
    document_id = document["id"]
    filename = document["filename"]
    try:
        repo.update_document(document_id, status="processing", error=None)
        data = await asyncio.to_thread(repo.download_file, document["storage_path"])
        text = await asyncio.to_thread(parse_document, filename, data)
        chunks = chunk_text(text)
        if not chunks:
            raise IngestionError("No text found in file")

        # Record manager: only chunks whose hash is not already stored get embedded.
        hashes = [sha256_hex(c) for c in chunks]
        plan = plan_chunks(repo.list_chunks(document_id), hashes)
        if plan.to_embed:
            embeddings = await llm.embed([chunks[i] for i in plan.to_embed])
            rows = [
                {
                    "chunk_index": i,
                    "content": chunks[i],
                    "content_hash": hashes[i],
                    "embedding": embedding,
                }
                for i, embedding in zip(plan.to_embed, embeddings, strict=True)
            ]
            await asyncio.to_thread(repo.insert_chunks, document_id, rows)
        for chunk_id, position in plan.to_move:
            repo.update_chunk_index(chunk_id, position)
        if plan.to_delete:
            repo.delete_chunks(plan.to_delete)

        metadata = await extract_metadata(filename, text)
        repo.set_document_content(document_id, text)
    except Exception as exc:
        message = str(exc) if isinstance(exc, IngestionError) else f"Ingestion failed: {exc}"
        return repo.update_document(document_id, status="failed", error=message[:500])
    return repo.update_document(
        document_id,
        status="completed",
        error=None,
        chunk_count=len(chunks),
        metadata=metadata,
        ingest_stats=plan.stats,
    )
