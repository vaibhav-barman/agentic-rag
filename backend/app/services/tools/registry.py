"""Tool registry for the main agent. Add a tool by listing it here.

Kept out of the package __init__ so `base` can be imported without loading every tool."""

from app.services.tools.analyze import AnalyzeDocumentTool
from app.services.tools.base import Tool, ToolContext, ToolOutput
from app.services.tools.file_search import FileSearchTool
from app.services.tools.sql import QueryDatabaseTool
from app.services.tools.web import WebSearchTool

MAIN_TOOLS: list[Tool] = [
    FileSearchTool(),
    AnalyzeDocumentTool(),
    QueryDatabaseTool(),
    WebSearchTool(),
]


def available_tools(ctx: ToolContext) -> list[Tool]:
    return [tool for tool in MAIN_TOOLS if tool.available(ctx)]


__all__ = ["MAIN_TOOLS", "Tool", "ToolContext", "ToolOutput", "available_tools"]
