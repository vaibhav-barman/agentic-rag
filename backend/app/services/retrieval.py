"""Retrieval: hybrid search in Postgres, then an LLM reranker.

1. The database returns RETRIEVAL_CANDIDATES chunks. In "hybrid" mode a keyword
   leg (full-text search) and a vector leg (pgvector) are fused with Reciprocal
   Rank Fusion, so exact terms (codes, names) and paraphrases both surface.
2. The reranker reads the query next to each candidate, which a vector
   comparison cannot do, scores them 0-1, and keeps the best FILE_SEARCH_TOP_K.
"""

import logging

from pydantic import BaseModel, Field

from app.config import get_settings
from app.services import llm

logger = logging.getLogger(__name__)

RERANK_PROMPT = (
    "You are a search reranker. Score how well each passage helps answer the query, "
    "from 0 (irrelevant) to 1 (directly answers it). Judge only what the passage says. "
    "Return a score for every passage index."
)
RERANK_PASSAGE_CHARS = 1500


class RerankItem(BaseModel):
    index: int = Field(description="The passage number as given.")
    score: float = Field(description="Relevance from 0 to 1.")


class RerankResult(BaseModel):
    rankings: list[RerankItem]


def _to_source(hit: dict) -> dict:
    score = hit.get("score")
    return {
        "type": "document",
        "document_id": hit["document_id"],
        "filename": hit["filename"],
        "chunk_index": hit["chunk_index"],
        "content": hit["content"],
        "similarity": round(float(hit["similarity"]), 4),
        "score": round(float(score), 4) if score is not None else None,
        "vector_rank": hit.get("vector_rank"),
        "keyword_rank": hit.get("keyword_rank"),
    }


async def rerank(query: str, sources: list[dict], top_k: int) -> list[dict]:
    """Reorder by LLM relevance score; on any failure keep the database order."""
    settings = get_settings()
    passages = "\n\n".join(
        f"[{i}] ({s['filename']})\n{s['content'][:RERANK_PASSAGE_CHARS]}"
        for i, s in enumerate(sources)
    )
    messages = [
        {"role": "system", "content": RERANK_PROMPT},
        {"role": "user", "content": f"Query: {query}\n\nPassages:\n\n{passages}"},
    ]
    try:
        result: RerankResult = await llm.complete_structured(messages, RerankResult)
    except Exception as exc:
        logger.warning("Rerank failed, keeping fused order: %s", exc)
        return sources[:top_k]

    scores: dict[int, float] = {}
    for item in result.rankings:
        if 0 <= item.index < len(sources):
            scores.setdefault(item.index, max(0.0, min(1.0, item.score)))
    if not scores:
        return sources[:top_k]
    ranked = sorted(scores, key=lambda i: scores[i], reverse=True)
    return [
        {**sources[i], "score": round(scores[i], 4)}
        for i in ranked
        if scores[i] >= settings.rerank_min_score
    ][:top_k]


async def search(
    repo,
    query: str,
    *,
    metadata_filter: dict | None = None,
    filename: str | None = None,
    document_id: str | None = None,
    top_k: int | None = None,
) -> list[dict]:
    """Best chunks for `query` from the user's documents, as source dicts."""
    settings = get_settings()
    top_k = top_k or settings.file_search_top_k
    [vector] = await llm.embed([query])
    candidates = repo.search_chunks(
        query,
        vector,
        match_count=max(settings.retrieval_candidates, top_k) if settings.rerank_enabled else top_k,
        mode=settings.search_mode,
        metadata_filter=metadata_filter or None,
        filename=filename,
        document_id=document_id,
        min_similarity=settings.retrieval_min_similarity,
    )
    sources = [_to_source(hit) for hit in candidates]
    if settings.rerank_enabled and len(sources) > 1:
        return await rerank(query, sources, top_k)
    return sources[:top_k]


def format_sources(sources: list[dict]) -> str:
    """Tool result text given to the model."""
    if not sources:
        return "No matching excerpts found in the user's documents."
    return "\n\n".join(
        f"[{i}] {s['filename']} (passage {s['chunk_index']}):\n{s['content']}"
        for i, s in enumerate(sources, start=1)
    )
