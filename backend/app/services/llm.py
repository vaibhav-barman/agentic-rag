"""The only module that talks to the LLM provider (Google Gemini API).

Uses the raw `openai` SDK pointed at Gemini's OpenAI-compatible endpoint (GEMINI_BASE_URL).
LangSmith tracing uses @traceable on the functions below rather than
`langsmith.wrappers.wrap_openai`: the wrapper crashes on Gemini's streamed tool
calls, which arrive without an `index`.
"""

import json
import os
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from functools import lru_cache

from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree
from openai import AsyncOpenAI

from app.config import get_settings


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str = ""
    # Provider data that must be echoed back with the call (Gemini's thought_signature).
    extra_content: dict | None = None

    def parsed_arguments(self) -> dict:
        try:
            value = json.loads(self.arguments or "{}")
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}


@dataclass
class StreamEvent:
    """One item from `stream_chat`: a text delta, or the final tool calls."""

    type: str  # "delta" | "tool_calls" | "usage"
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict | None = None


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
    return AsyncOpenAI(
        base_url=settings.gemini_base_url,
        api_key=settings.gemini_api_key or "missing-key",
    )


def _tag_llm_run() -> None:
    run = get_current_run_tree()
    if run is not None:
        run.metadata.update({"ls_provider": "google", "ls_model_name": get_settings().gemini_model})


def _reduce_stream(events: Sequence[StreamEvent]) -> dict:
    """What the LangSmith llm run shows as output: the full message + token usage."""
    text = "".join(e.text for e in events if e.type == "delta")
    calls = [c for e in events if e.type == "tool_calls" for c in e.tool_calls]
    message: dict = {"role": "assistant", "content": text or None}
    if calls:
        message["tool_calls"] = [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
            for c in calls
        ]
    out: dict = {"choices": [{"message": message}]}
    usage = next((e.usage for e in events if e.type == "usage" and e.usage), None)
    if usage:
        out["usage_metadata"] = usage
    return out


@traceable(name="gemini_chat", run_type="llm", reduce_fn=_reduce_stream)
async def stream_chat(
    messages: list[dict], tools: list[dict] | None = None
) -> AsyncIterator[StreamEvent]:
    """Stream a chat completion: yields text deltas, then tool calls (if any), then usage."""
    _tag_llm_run()
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
    usage: dict | None = None
    async for chunk in stream:
        if chunk.usage:
            usage = {
                "input_tokens": chunk.usage.prompt_tokens,
                "output_tokens": chunk.usage.completion_tokens,
                "total_tokens": chunk.usage.total_tokens,
            }
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
            extra = (tc.model_extra or {}).get("extra_content")
            if extra:
                call.extra_content = extra
    if calls:
        yield StreamEvent(type="tool_calls", tool_calls=[calls[i] for i in sorted(calls)])
    if usage:
        yield StreamEvent(type="usage", usage=usage)


@traceable(name="gemini_embed", run_type="embedding")
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
