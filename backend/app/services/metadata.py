"""LLM metadata extraction: one structured-output call per document at ingestion."""

import logging

from app.config import get_settings
from app.schemas import DocumentMetadata
from app.services import llm

logger = logging.getLogger(__name__)

PROMPT = (
    "You catalogue documents for a search system. Read the start of the document below "
    "and fill in its metadata. Base every field on the text itself; do not guess facts "
    "that are not there. Topics are short lowercase tags a person might filter by."
)


async def extract_metadata(filename: str, text: str) -> dict:
    """Return DocumentMetadata as a dict, or {} if extraction is off or fails.

    Never raises: a document without metadata is still searchable.
    """
    settings = get_settings()
    if not settings.metadata_extraction_enabled:
        return {}
    sample = text[: settings.metadata_sample_chars]
    messages = [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": f"Filename: {filename}\n\n<document>\n{sample}\n</document>"},
    ]
    try:
        metadata = await llm.complete_structured(messages, DocumentMetadata)
        return metadata.model_dump(exclude_none=True)
    except Exception as exc:
        logger.warning("Metadata extraction failed for %s: %s", filename, exc)
        return {}
