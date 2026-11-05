"""The only module that talks to the LLM provider (Google Gemini API).

Uses the raw `openai` SDK pointed at Gemini's OpenAI-compatible endpoint (GEMINI_BASE_URL). When LangSmith tracing
is enabled the client is wrapped so every call is traced.
"""

import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from functools import lru_cache

from openai import AsyncOpenAI

from app.config import get_settings


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str = ""

    def parsed_arguments(self) -> dict:
        try:
            value = json.loads(self.arguments or "{}")
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}


@dataclass
class StreamEvent:
    """One item from `stream_chat`: a text delta, or the final tool calls."""

    type: str  # "delta" | "tool_calls"
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


def configure_langsmith_env() -> None:
    """Called at app startup, before any @traceable function runs."""
    # The langsmith SDK reads these from the process environment.
    settings = get_settings()
    os.environ["LANGSMITH_TRACING"] = "true" if settings.langsmith_tracing else "false"
    if settings.langsmith_api_key:
        os.environ.setdefault("LANGSMITH_API_KEY", settings.langsmith_api_key)
    if settings.langsmith_project:
        os.environ.setdefault("LANGSMITH_PROJECT", settings.langsmith_project)


@lru_cache
def get_client() -> AsyncOpenAI:
    settings = get_settings()
    client = AsyncOpenAI(
        base_url=settings.gemini_base_url,
        api_key=settings.gemini_api_key or "missing-key",
    )
    configure_langsmith_env()
    if settings.langsmith_tracing and settings.langsmith_api_key:
        from langsmith.wrappers import wrap_openai

        client = wrap_openai(client)
    return client


async def stream_chat(
    messages: list[dict], tools: list[dict] | None = None
) -> AsyncIterator[StreamEvent]:
    """Stream a chat completion: yields text deltas, then (if any) the tool calls."""
    settings = get_settings()
    kwargs: dict = {
        "model": settings.gemini_model,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if tools:
        kwargs["tools"] = tools
    stream = await get_client().chat.completions.create(**kwargs)

    calls: dict[int, ToolCall] = {}
    async for chunk in stream:
        if not chunk.choices:
            continue  # usage-only chunk
        delta = chunk.choices[0].delta
        if delta.content:
            yield StreamEvent(type="delta", text=delta.content)
        for tc in delta.tool_calls or []:
            # Gemini may omit `index` and send each call whole; key those by position.
            key = tc.index if tc.index is not None else len(calls)
            call = calls.setdefault(key, ToolCall(id=tc.id or f"call_{key}", name=""))
            if tc.id:
                call.id = tc.id
            if tc.function and tc.function.name:
                call.name = tc.function.name
            if tc.function and tc.function.arguments:
                call.arguments += tc.function.arguments
    if calls:
        yield StreamEvent(type="tool_calls", tool_calls=[calls[i] for i in sorted(calls)])


async def embed(texts: list[str]) -> list[list[float]]:
    """Embed texts in batches; returns one vector per input, in order."""
    settings = get_settings()
    model = settings.gemini_embedding_model
    extra: dict = {}
    # Gemini and OpenAI text-embedding-3 models can be shortened to match the DB column.
    if "gemini-embedding" in model or "text-embedding-3" in model:
        extra["dimensions"] = settings.embedding_dimensions
    vectors: list[list[float]] = []
    for start in range(0, len(texts), 64):
        batch = texts[start : start + 64]
        response = await get_client().embeddings.create(model=model, input=batch, **extra)
        ordered = sorted(response.data, key=lambda d: d.index)
        vectors.extend(d.embedding for d in ordered)
    if vectors and len(vectors[0]) != settings.embedding_dimensions:
        raise ValueError(
            f"Embedding model {model} returned {len(vectors[0])} dims; "
            f"the database expects EMBEDDING_DIMENSIONS={settings.embedding_dimensions}"
        )
    return vectors
