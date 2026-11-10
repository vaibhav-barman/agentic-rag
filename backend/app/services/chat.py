"""One chat turn of the main agent: memory from stored history, tools, streaming.

Yields SSE-ready events:
  ("delta", {text})
  ("tool_call", {id, name, arguments, parent_id})      parent_id set for sub-agent steps
  ("tool_result", {id, ok, summary, data, parent_id})
  ("subagent_delta", {parent_id, text})
  ("sources", {query, sources})
  ("done", {message_id, title})
  ("error", {message})
"""

from collections.abc import AsyncIterator

from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from app.config import get_settings
from app.services.agent import StepRecorder, public_sources, run_agent
from app.services.tools.base import Tool, ToolContext
from app.services.tools.registry import available_tools

BASE_PROMPT = (
    "You are Glossa, a helpful assistant in a retrieval-augmented chat app. "
    "Use the conversation history for context. Answer in Markdown."
)
NO_TOOLS_PROMPT = (
    " The user has not uploaded any documents yet, so answer from your own knowledge "
    "and say so if you are unsure."
)
ROUTING_PROMPT = (
    "\n\nChoosing a tool: the user's documents come first. If they do not contain the "
    "answer, say so plainly instead of guessing"
)
LIBRARY_LIMIT = 50


def make_title(text: str, limit: int = 60) -> str:
    title = " ".join(text.split())
    return title if len(title) <= limit else title[: limit - 1].rstrip() + "…"


def build_system_prompt(tools: list[Tool], library: list[dict]) -> str:
    """Base instructions + guidance for each available tool + the user's document list."""
    if not tools:
        return BASE_PROMPT + NO_TOOLS_PROMPT
    names = {t.name for t in tools}
    prompt = BASE_PROMPT + "\n\nTools:\n" + "\n".join(f"- {t.guidance}" for t in tools)
    prompt += ROUTING_PROMPT
    prompt += (
        ", or fall back to web_search and make clear the answer is from the web."
        if "web_search" in names
        else "."
    )
    if library:
        lines = []
        for doc in library:
            meta = doc.get("metadata") or {}
            parts = [f"- {doc['filename']} (id: {doc['id']}"]
            if meta.get("document_type"):
                parts.append(f", type: {meta['document_type']}")
            if meta.get("topics"):
                parts.append(f", topics: {', '.join(meta['topics'])}")
            line = "".join(parts) + ")"
            if meta.get("summary"):
                line += f": {meta['summary']}"
            lines.append(line)
        prompt += "\n\nThe user's documents:\n" + "\n".join(lines)
    return prompt


def _trace_inputs(inputs: dict) -> dict:
    # Never send the repo (it holds the user's access token) to LangSmith.
    thread = inputs.get("thread") or {}
    return {"thread_id": thread.get("id"), "user_content": inputs.get("user_content")}


@traceable(name="chat_turn", run_type="chain", process_inputs=_trace_inputs)
async def run_chat_turn(repo, thread: dict, user_content: str) -> AsyncIterator[tuple[str, dict]]:
    settings = get_settings()
    thread_id = thread["id"]

    ctx = ToolContext(
        repo=repo, user_content=user_content, library=repo.library_overview(LIBRARY_LIMIT)
    )
    tools = available_tools(ctx)

    # Memory: the stored history (which already includes this user message).
    # The API is stateless, so the last N messages are sent on every turn.
    history = repo.list_messages(thread_id, limit=settings.chat_history_limit)
    messages: list[dict] = [
        {"role": "system", "content": build_system_prompt(tools, ctx.library)}
    ] + [{"role": m["role"], "content": m["content"]} for m in history]

    run = get_current_run_tree()
    if run is not None:
        run.metadata.update(
            {
                "user_id": repo.user_id,
                "thread_id": thread_id,
                "tools_offered": [t.name for t in tools],
                "file_search_enabled": any(t.name == "file_search" for t in tools),
                "model": settings.gemini_model,
            }
        )

    answer = ""
    all_sources: list[dict] = []
    recorder = StepRecorder()
    try:
        async for event, data in run_agent(
            messages, tools, ctx, max_rounds=settings.max_tool_rounds
        ):
            if event == "final":
                continue
            recorder.record(event, data)
            if event == "delta":
                answer += data["text"]
            elif event == "sources":
                all_sources.extend(data["sources"])
            yield event, data
    except Exception as exc:
        yield "error", {"message": f"The model request failed: {exc}"}
        if not answer:
            return

    steps = recorder.steps
    if run is not None:
        used = [s["name"] for s in steps]
        run.metadata["tools_used"] = used
        run.metadata["file_search_used"] = "file_search" in used

    if not answer.strip():
        answer = "_(The model returned an empty response.)_"
    saved = repo.add_message(
        thread_id,
        "assistant",
        answer,
        sources=public_sources(all_sources) or None,
        steps=steps or None,
    )
    title = thread.get("title")
    if not title:
        title = make_title(user_content)
        repo.update_thread(thread_id, title=title)
    else:
        repo.update_thread(thread_id)
    yield "done", {"message_id": saved["id"], "title": title}
