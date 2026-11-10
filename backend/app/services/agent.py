"""The agent loop shared by the main agent and sub-agents.

Stream a completion; if the model asked for tools, run them, append the results
and go again; stop when it answers in text (or the round budget runs out).
Everything the UI should show is yielded as an event while it happens.
"""

import json
import uuid
from collections.abc import AsyncIterator

from app.services import llm
from app.services.tools.base import Event, Tool, ToolContext, ToolOutput

SOURCE_PREVIEW_CHARS = 400


def public_sources(sources: list[dict]) -> list[dict]:
    """Dedupe and trim content to a preview: what the browser gets and what is stored."""
    seen: set[tuple] = set()
    out = []
    for s in sources:
        key = (s.get("document_id"), s.get("chunk_index"), s.get("url"))
        if key in seen:
            continue
        seen.add(key)
        out.append({**s, "content": (s.get("content") or "")[:SOURCE_PREVIEW_CHARS]})
    return out


def _assistant_tool_message(tool_calls: list[llm.ToolCall]) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": c.arguments or "{}"},
                # Gemini rejects the follow-up unless its thought_signature is echoed.
                **({"extra_content": c.extra_content} if c.extra_content else {}),
            }
            for c in tool_calls
        ],
    }


async def run_agent(
    messages: list[dict],
    tools: list[Tool],
    ctx: ToolContext,
    *,
    max_rounds: int,
    parent_id: str | None = None,
) -> AsyncIterator[Event]:
    """Run the loop over `messages` (mutated in place).

    Yields, in order of occurrence:
      ("delta", {text})                       main agent text
      ("subagent_delta", {parent_id, text})   sub-agent text (when parent_id is set)
      ("tool_call", {id, name, arguments, parent_id})
      ("tool_result", {id, ok, summary, data, parent_id})
      ("sources", {query, sources})
      ("final", {text})                       always last; for the caller, not the browser
    """
    schemas = [t.schema(ctx) for t in tools] or None
    by_name = {t.name: t for t in tools}
    answer = ""

    for round_no in range(max_rounds + 1):
        # On the last round, withhold tools so the model must answer.
        round_tools = schemas if round_no < max_rounds else None
        tool_calls: list[llm.ToolCall] = []
        async for event in llm.stream_chat(messages, round_tools):
            if event.type == "delta":
                answer += event.text
                if parent_id is None:
                    yield "delta", {"text": event.text}
                else:
                    yield "subagent_delta", {"parent_id": parent_id, "text": event.text}
            elif event.type == "tool_calls":
                tool_calls = event.tool_calls
        if not tool_calls:
            break

        messages.append(_assistant_tool_message(tool_calls))
        for call in tool_calls:
            # Our own id: provider call ids can repeat between rounds.
            step_id = uuid.uuid4().hex[:12]
            args = call.parsed_arguments()
            yield (
                "tool_call",
                {"id": step_id, "name": call.name, "arguments": args, "parent_id": parent_id},
            )

            output: ToolOutput | None = None
            tool = by_name.get(call.name)
            if tool is None:
                output = ToolOutput(
                    content=json.dumps({"error": f"Unknown tool {call.name}"}),
                    summary=f"Unknown tool {call.name}",
                    ok=False,
                )
            else:
                try:
                    async for item in tool.run(ctx, step_id, args):
                        if isinstance(item, ToolOutput):
                            output = item
                        else:
                            yield item
                except Exception as exc:
                    output = ToolOutput(
                        content=f"The {call.name} tool failed: {exc}",
                        summary=f"Failed: {exc}"[:200],
                        ok=False,
                    )
            if output is None:
                output = ToolOutput(content="(no result)", summary="No result", ok=False)

            yield (
                "tool_result",
                {
                    "id": step_id,
                    "ok": output.ok,
                    "summary": output.summary,
                    "data": output.data,
                    "parent_id": parent_id,
                },
            )
            if output.sources:
                yield (
                    "sources",
                    {"query": args.get("query"), "sources": public_sources(output.sources)},
                )
            messages.append({"role": "tool", "tool_call_id": call.id, "content": output.content})

    yield "final", {"text": answer}


class StepRecorder:
    """Builds the step list saved with the assistant message from the event stream."""

    def __init__(self) -> None:
        self._steps: dict[str, dict] = {}

    def record(self, event: str, data: dict) -> None:
        if event == "tool_call":
            self._steps[data["id"]] = {**data}
        elif event == "tool_result" and data["id"] in self._steps:
            step = self._steps[data["id"]]
            step.update(ok=data["ok"], summary=data["summary"], data=data["data"])
        elif event == "subagent_delta" and data["parent_id"] in self._steps:
            step = self._steps[data["parent_id"]]
            step["text"] = (step.get("text") or "") + data["text"]

    @property
    def steps(self) -> list[dict]:
        return list(self._steps.values())
