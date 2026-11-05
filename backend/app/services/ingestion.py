"""Manual-upload ingestion: extract text -> chunk -> embed -> store chunks."""

import io
from pathlib import PurePath

from app.config import get_settings
from app.services import llm

ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf"}


class IngestionError(Exception):
    pass


def extension_of(filename: str) -> str:
    return PurePath(filename).suffix.lower()


def extract_text(filename: str, data: bytes) -> str:
    ext = extension_of(filename)
    if ext in {".txt", ".md"}:
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IngestionError("File is not valid UTF-8 text") from exc
    if ext == ".pdf":
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(data))
            return "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:  # pypdf raises many types
            raise IngestionError(f"Could not read PDF: {exc}") from exc
    raise IngestionError(f"Unsupported file type: {ext or 'none'}")


def chunk_text(text: str, size: int | None = None, overlap: int | None = None) -> list[str]:
    """Split into ~`size`-char chunks with `overlap` chars shared between neighbours.

    Breaks at the last paragraph/sentence/word boundary inside the window when one
    exists in its second half, so chunks rarely cut words in two.
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
            for sep in ("\n\n", ". ", "\n", " "):
                cut = window.rfind(sep)
                if cut > size // 2:
                    end = start + cut + len(sep)
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


async def ingest(repo, document_id: str, filename: str, data: bytes) -> dict:
    """Process one uploaded file; returns the updated document row."""
    try:
        chunks = chunk_text(extract_text(filename, data))
        if not chunks:
            raise IngestionError("No text found in file")
        embeddings = await llm.embed(chunks)
        repo.insert_chunks(document_id, chunks, embeddings)
    except Exception as exc:
        message = str(exc) if isinstance(exc, IngestionError) else f"Ingestion failed: {exc}"
        return repo.update_document(document_id, status="failed", error=message[:500])
    return repo.update_document(
        document_id, status="completed", error=None, chunk_count=len(chunks)
    )
