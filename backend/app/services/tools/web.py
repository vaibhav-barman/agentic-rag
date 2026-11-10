"""web_search: the fallback when the user's documents do not have the answer (Tavily)."""

import httpx

from app.config import get_settings
from app.services.tools.base import Tool, ToolContext, ToolOutput, function_schema

TAVILY_URL = "https://api.tavily.com/search"
SNIPPET_CHARS = 700
# Tests replace this with an httpx.MockTransport.
transport: httpx.AsyncBaseTransport | None = None


async def tavily_search(query: str) -> list[dict]:
    """Top web results as source dicts: {type, title, url, content, score}."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=20, transport=transport) as client:
        response = await client.post(
            TAVILY_URL,
            headers={"Authorization": f"Bearer {settings.tavily_api_key}"},
            json={
                "query": query,
                "max_results": settings.web_search_max_results,
                "search_depth": "basic",
            },
        )
        response.raise_for_status()
    return [
        {
            "type": "web",
            "title": r.get("title") or r.get("url") or "Untitled",
            "url": r["url"],
            "content": (r.get("content") or "")[:SNIPPET_CHARS],
            "score": round(float(r["score"]), 4) if r.get("score") is not None else None,
        }
        for r in response.json().get("results", [])
        if r.get("url")
    ]


class WebSearchTool(Tool):
    name = "web_search"
    guidance = (
        "Use web_search only as a fallback: when the user's documents do not contain the "
        "answer, or the question is about current or public information. Say that the "
        "answer comes from the web and cite the pages as Markdown links."
    )

    def available(self, ctx: ToolContext) -> bool:
        return bool(get_settings().tavily_api_key)

    def schema(self, ctx: ToolContext) -> dict:
        return function_schema(
            self.name,
            "Search the public web and return the top results with snippets and URLs.",
            {"query": {"type": "string", "description": "The web search query."}},
            ["query"],
        )

    async def run(self, ctx: ToolContext, step_id: str, args: dict):
        query = str(args.get("query") or ctx.user_content)
        try:
            results = await tavily_search(query)
        except httpx.HTTPError as exc:
            yield ToolOutput(
                content=f"Web search failed: {exc}", summary="Web search failed", ok=False
            )
            return
        if not results:
            yield ToolOutput(content="No web results found.", summary="No web results")
            return
        content = "\n\n".join(
            f"[{i}] {r['title']}\n{r['url']}\n{r['content']}" for i, r in enumerate(results, 1)
        )
        yield ToolOutput(
            content=content,
            summary=f"{len(results)} web result{'s' if len(results) != 1 else ''}",
            sources=results,
            data={"results": [{"title": r["title"], "url": r["url"]} for r in results]},
        )
