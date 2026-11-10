"""Document sub-agent: reads one whole document in its own, isolated context.

Why isolate? A whole document can be hundreds of thousands of characters. Putting
it in the main conversation would crowd out the chat history and be re-sent on
every later turn. The sub-agent gets a fresh context holding only its
instructions, the document and the task; the main agent gets back just the
answer. Nothing from the main conversation is passed in.
"""

from collections.abc import AsyncIterator

from langsmith import traceable

from app.config import get_settings
from app.services import retrieval
from app.services.agent import run_agent
from app.services.tools.base import Event, Tool, ToolContext, ToolOutput, function_schema

SUBAGENT_PROMPT = (
    "You are a document analyst working for another assistant. You are given one "
    "document and a task about it. Work only from the document: do not use outside "
    "knowledge, and say so if the document does not cover something. Be thorough and "
    "specific (names, numbers, dates, section titles), and cover the whole document, "
    "not just its beginning. Your reply goes back to the assistant that asked, so "
    "answer the task directly in Markdown without preamble."
)


class SearchInDocumentTool(Tool):
    name = "search_in_document"

    def __init__(self, document: dict):
        self.document = document

    def schema(self, ctx: ToolContext) -> dict:
        return function_schema(
            self.name,
            "Search inside this document only and return the most relevant passages.",
            {"query": {"type": "string", "description": "What to look for."}},
            ["query"],
        )

    async def run(self, ctx: ToolContext, step_id: str, args: dict):
        query = str(args.get("query") or "")
        sources = await retrieval.search(ctx.repo, query, document_id=self.document["id"])
        yield ToolOutput(
            content=retrieval.format_sources(sources),
            summary=f"{len(sources)} passage{'s' if len(sources) != 1 else ''}",
            sources=sources,
        )


class ReadPassagesTool(Tool):
    name = "read_passages"
    MAX_SPAN = 20

    def __init__(self, document: dict):
        self.document = document

    def schema(self, ctx: ToolContext) -> dict:
        last = max(self.document.get("chunk_count", 1) - 1, 0)
        return function_schema(
            self.name,
            f"Read consecutive passages of this document by number (0 to {last}), "
            f"at most {self.MAX_SPAN} at a time.",
            {
                "start": {"type": "integer", "description": "First passage number."},
                "end": {"type": "integer", "description": "Last passage number (inclusive)."},
            },
            ["start", "end"],
        )

    async def run(self, ctx: ToolContext, step_id: str, args: dict):
        try:
            start = max(int(args.get("start", 0)), 0)
            end = max(int(args.get("end", start)), start)
        except TypeError, ValueError:
            yield ToolOutput(
                content="start and end must be integers.", summary="Bad range", ok=False
            )
            return
        end = min(end, start + self.MAX_SPAN - 1)
        chunks = ctx.repo.get_chunks(self.document["id"], start, end)
        if not chunks:
            yield ToolOutput(
                content="No passages in that range.", summary="No passages in that range"
            )
            return
        yield ToolOutput(
            content="\n\n".join(f"[passage {c['chunk_index']}]\n{c['content']}" for c in chunks),
            summary=f"Read passages {chunks[0]['chunk_index']}-{chunks[-1]['chunk_index']}",
        )


def _trace_inputs(inputs: dict) -> dict:
    # Never send the context (it holds the user's access token) to LangSmith.
    document = inputs.get("document") or {}
    return {"document": document.get("filename"), "task": inputs.get("task")}


def _load_text(repo, document: dict) -> str:
    text = repo.get_document_content(document["id"])
    if text is None:
        # Ingested before full text was stored: rebuild from the chunks.
        text = "\n\n".join(c["content"] for c in repo.get_chunks(document["id"]))
    return text


@traceable(name="sub_agent", run_type="chain", process_inputs=_trace_inputs)
async def run_subagent(
    ctx: ToolContext, step_id: str, document: dict, task: str
) -> AsyncIterator[Event | ToolOutput]:
    """Yield the sub-agent's events (tagged with parent_id=step_id), then its answer."""
    settings = get_settings()
    text = _load_text(ctx.repo, document)
    truncated = len(text) > settings.subagent_max_chars
    shown = text[: settings.subagent_max_chars]
    note = ""
    if truncated:
        note = (
            f"\n\nNote: the document is {len(text):,} characters long and only the first "
            f"{len(shown):,} are shown above. Use read_passages and search_in_document "
            "to cover the rest before answering."
        )
    # A fresh context: no chat history, no library overview, only this document and task.
    messages: list[dict] = [
        {"role": "system", "content": SUBAGENT_PROMPT},
        {
            "role": "user",
            "content": (
                f"Document: {document['filename']} "
                f"({document.get('chunk_count', 0)} passages)\n\n"
                f"<document>\n{shown}\n</document>{note}\n\nTask: {task}"
            ),
        },
    ]
    tools: list[Tool] = [SearchInDocumentTool(document), ReadPassagesTool(document)]

    answer = ""
    async for event, data in run_agent(
        messages, tools, ctx, max_rounds=settings.subagent_max_rounds, parent_id=step_id
    ):
        if event == "final":
            answer = data["text"]
        else:
            yield event, data

    yield ToolOutput(
        content=answer.strip() or "The sub-agent returned no answer.",
        summary=f"Read {document['filename']} ({len(text):,} characters)",
        ok=bool(answer.strip()),
        data={"document": document["filename"], "characters": len(text), "truncated": truncated},
    )
