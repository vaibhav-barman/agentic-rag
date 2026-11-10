"""analyze_document: hand a whole-document task to a sub-agent (services/subagent.py)."""

from app.services.subagent import run_subagent
from app.services.tools.base import Tool, ToolContext, ToolOutput, function_schema


def resolve_document(library: list[dict], reference: str) -> dict | None:
    """Find a document by id, exact filename, or a filename fragment."""
    ref = reference.strip().lower()
    if not ref:
        return None
    for doc in library:
        if doc["id"].lower() == ref or doc["filename"].lower() == ref:
            return doc
    matches = [d for d in library if ref in d["filename"].lower()]
    return matches[0] if len(matches) == 1 else None


class AnalyzeDocumentTool(Tool):
    name = "analyze_document"
    guidance = (
        "Use analyze_document when a request needs a whole document rather than a few "
        "excerpts: summarising it, listing everything of some kind in it, reviewing or "
        "critiquing it, or comparing documents (call it once per document). A sub-agent "
        "reads the full text and reports back; base your answer on its report."
    )

    def available(self, ctx: ToolContext) -> bool:
        return bool(ctx.library)

    def schema(self, ctx: ToolContext) -> dict:
        return function_schema(
            self.name,
            "Delegate a task that needs one entire document to a sub-agent that reads "
            "the full text in its own context and returns its findings.",
            {
                "document_id": {
                    "type": "string",
                    "description": "The id of the document, from the list of the user's documents.",
                },
                "task": {
                    "type": "string",
                    "description": (
                        "Self-contained instructions for the sub-agent. It sees only the "
                        "document and this task, not the conversation."
                    ),
                },
            },
            ["document_id", "task"],
        )

    async def run(self, ctx: ToolContext, step_id: str, args: dict):
        reference = str(args.get("document_id") or "")
        document = resolve_document(ctx.library, reference)
        if document is None:
            names = ", ".join(f"{d['filename']} (id {d['id']})" for d in ctx.library[:20])
            yield ToolOutput(
                content=f"No document matches '{reference}'. Available: {names}",
                summary=f"No document matches '{reference}'",
                ok=False,
            )
            return
        task = str(args.get("task") or ctx.user_content)
        async for item in run_subagent(ctx, step_id, document, task):
            yield item
