"""What a tool is. The agent loop (services/agent.py) only knows this interface."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

# An event for the browser: ("tool_call", {...}), ("subagent_delta", {...}), ...
Event = tuple[str, dict]


@dataclass
class ToolContext:
    """Everything a tool may need for one chat turn."""

    repo: Any
    user_content: str = ""
    # Completed documents with metadata (see Repo.library_overview).
    library: list[dict] = field(default_factory=list)


@dataclass
class ToolOutput:
    """The result of one tool call."""

    content: str  # what the model reads
    summary: str  # one line for the step timeline in the UI
    ok: bool = True
    sources: list[dict] = field(default_factory=list)  # attribution shown beside the answer
    data: dict | None = None  # small structured detail for the UI (SQL, rows, ...)


class Tool:
    name: str = ""
    # One or two sentences added to the system prompt when the tool is available.
    guidance: str = ""

    def available(self, ctx: ToolContext) -> bool:
        return True

    def schema(self, ctx: ToolContext) -> dict:
        """The function definition sent to the model."""
        raise NotImplementedError

    def run(self, ctx: ToolContext, step_id: str, args: dict) -> AsyncIterator[Event | ToolOutput]:
        """Async generator: may yield events while working, then one ToolOutput."""
        raise NotImplementedError


def function_schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }
