"""One chat turn: memory from stored history, optional file_search tool, streaming.

Yields SSE-ready events: ("delta", {"text"}), ("sources", {"sources"}),
("done", {"message_id", "title"}), ("error", {"message"}).
"""

import json
from collections.abc import AsyncIterator

from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from app.config import get_settings
from app.services import llm

SYSTEM_PROMPT = (
    "You are a helpful assistant in a retrieval-augmented chat app. "
    "Use the conversation history for context. "
    "When the user asks about their documents or about facts you may not know, "
    "call the file_search tool and ground your answer in the returned excerpts, "
    "naming the source file. If the excerpts don't contain the answer, say so. "
    "Answer in Markdown."
)

FILE_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "file_search",
        "description": (
            "Search the user's uploaded documents and return the most relevant excerpts."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for, in plain words."}
            },
            "required": ["query"],
        },
    },
}


def make_title(text: str, limit: int = 60) -> str:
    title = " ".join(text.split())
    return title if len(title) <= limit else title[: limit - 1].rstrip() + "…"


async def file_search(repo, query: str) -> list[dict]:
    """Embed the query and return the top chunks as source dicts."""
    settings = get_settings()
    [vector] = await llm.embed([query])
    hits = repo.match_chunks(vector, settings.file_search_top_k)
    return [
        {
            "document_id": h["document_id"],
            "filename": h["filename"],
            "chunk_index": h["chunk_index"],
            "content": h["content"],
            "similarity": round(float(h["similarity"]), 4),
        }
        for h in hits
    ]


def format_tool_result(sources: list[dict]) -> str:
    if not sources:
        return "No matching excerpts found in the user's documents."
    return "\n\n".join(
        f"[{i}] {s['filename']} (chunk {s['chunk_index']}):\n{s['content']}"
        for i, s in enumerate(sources, start=1)
    )


def _trace_inputs(inputs: dict) -> dict:
    # Never send the repo (it holds the user's access token) to LangSmith.
    thread = inputs.get("thread") or {}
    return {"thread_id": thread.get("id"), "user_content": inputs.get("user_content")}


@traceable(name="chat_turn", run_type="chain", process_inputs=_trace_inputs)
async def run_chat_turn(
    repo, thread: dict, user_content: str
) -> AsyncIterator[tuple[str, dict]]:
    settings = get_settings()
    thread_id = thread["id"]

    # Memory: the stored history (which already includes this user message).
    history = repo.list_messages(thread_id, limit=settings.chat_history_limit)
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}] + [
        {"role": m["role"], "content": m["content"]} for m in history
    ]

    file_search_enabled = repo.has_completed_documents()
    tools = [FILE_SEARCH_TOOL] if file_search_enabled else None
    run = get_current_run_tree()
    if run is not None:
        run.metadata.update(
            {
                "user_id": repo.user_id,
                "thread_id": thread_id,
                "file_search_enabled": file_search_enabled,
                "model": settings.openrouter_model,
            }
        )

    answer = ""
    all_sources: list[dict] = []
    file_search_used = False
    try:
        for round_no in range(settings.max_tool_rounds + 1):
            # On the last round, withhold tools so the model must answer.
            round_tools = tools if round_no < settings.max_tool_rounds else None
            tool_calls: list[llm.ToolCall] = []
            async for event in llm.stream_chat(messages, round_tools):
                if event.type == "delta":
                    answer += event.text
                    yield "delta", {"text": event.text}
                elif event.type == "tool_calls":
                    tool_calls = event.tool_calls
            if not tool_calls:
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.name, "arguments": c.arguments or "{}"},
                        }
                        for c in tool_calls
                    ],
                }
            )
            for call in tool_calls:
                if call.name == "file_search":
                    file_search_used = True
                    query = str(call.parsed_arguments().get("query") or user_content)
                    sources = await file_search(repo, query)
                    all_sources.extend(sources)
                    yield "sources", {"query": query, "sources": _public_sources(sources)}
                    result = format_tool_result(sources)
                else:
                    result = json.dumps({"error": f"Unknown tool {call.name}"})
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
    except Exception as exc:
        yield "error", {"message": f"The model request failed: {exc}"}
        if not answer:
            return

    if run is not None:
        run.metadata["file_search_used"] = file_search_used

    if not answer.strip():
        answer = "_(The model returned an empty response.)_"
    saved = repo.add_message(
        thread_id, "assistant", answer, sources=_public_sources(all_sources) or None
    )
    title = thread.get("title")
    if not title:
        title = make_title(user_content)
        repo.update_thread(thread_id, title=title)
    else:
        repo.update_thread(thread_id)
    yield "done", {"message_id": saved["id"], "title": title}


def _public_sources(sources: list[dict]) -> list[dict]:
    """Dedupe by (document, chunk) and trim content to a preview for the UI."""
    seen: set[tuple] = set()
    out = []
    for s in sources:
        key = (s["document_id"], s["chunk_index"])
        if key in seen:
            continue
        seen.add(key)
        out.append({**s, "content": s["content"][:400]})
    return out
