"""file_search: retrieval over the user's documents, optionally filtered by metadata."""

from app.services import retrieval
from app.services.tools.base import Tool, ToolContext, ToolOutput, function_schema


class FileSearchTool(Tool):
    name = "file_search"
    guidance = (
        "Use file_search for questions about the user's documents or facts you may not "
        "know. Ground the answer in the returned excerpts and name the source file. "
        "Only add filters when the user clearly restricts the question to a kind of "
        "document, a topic or a file."
    )

    def available(self, ctx: ToolContext) -> bool:
        return bool(ctx.library)

    def schema(self, ctx: ToolContext) -> dict:
        types = sorted({t for d in ctx.library if (t := d["metadata"].get("document_type"))})
        properties: dict = {
            "query": {"type": "string", "description": "What to look for, in plain words."},
            "filename": {
                "type": "string",
                "description": "Optional. Only search files whose name contains this text.",
            },
            "topic": {
                "type": "string",
                "description": "Optional. Only search documents tagged with this topic.",
            },
        }
        if types:
            properties["document_type"] = {
                "type": "string",
                "enum": types,
                "description": "Optional. Only search documents of this type.",
            }
        return function_schema(
            self.name,
            "Search the user's uploaded documents (keyword + semantic) and return the "
            "most relevant excerpts.",
            properties,
            ["query"],
        )

    async def run(self, ctx: ToolContext, step_id: str, args: dict):
        query = str(args.get("query") or ctx.user_content)
        metadata_filter: dict = {}
        if args.get("document_type"):
            metadata_filter["document_type"] = str(args["document_type"])
        if args.get("topic"):
            metadata_filter["topics"] = [" ".join(str(args["topic"]).lower().split())]
        filename = str(args["filename"]) if args.get("filename") else None

        sources = await retrieval.search(
            ctx.repo, query, metadata_filter=metadata_filter, filename=filename
        )
        note = ""
        if not sources and (metadata_filter or filename):
            # A filter the model guessed wrong should not hide the answer.
            sources = await retrieval.search(ctx.repo, query)
            if sources:
                note = "Nothing matched the filters, so these results are from all documents.\n\n"

        if sources:
            files = list(dict.fromkeys(s["filename"] for s in sources))
            summary = f"{len(sources)} passage{'s' if len(sources) != 1 else ''} from " + ", ".join(
                files[:3]
            )
            if len(files) > 3:
                summary += f" and {len(files) - 3} more"
        else:
            summary = "No matching passages"
        yield ToolOutput(
            content=note + retrieval.format_sources(sources),
            summary=summary,
            sources=sources,
            data={
                "filters": {**metadata_filter, **({"filename": filename} if filename else {})},
                "results": [
                    {
                        "filename": s["filename"],
                        "passage": s["chunk_index"],
                        "score": s["score"],
                        "vector_rank": s["vector_rank"],
                        "keyword_rank": s["keyword_rank"],
                    }
                    for s in sources
                ],
            },
        )
