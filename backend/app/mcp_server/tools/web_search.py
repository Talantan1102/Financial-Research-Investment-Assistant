"""MCP tool adapter — web_search.

Wraps app.tools.web_search.WebSearchTool (Bocha-based).

Exports:
  TOOL_DEF  — mcp.types.Tool metadata for the list_tools aggregator in server.py
  handle()  — async dispatch function for the call_tool aggregator in server.py
"""

from __future__ import annotations

import json
from typing import Any

from mcp.types import TextContent, Tool

TOOL_DEF = Tool(
    name="web_search",
    description=(
        "Search the web for latest information via Bocha API. "
        "Args: query (str), search_type ('news' | 'industry' | 'report', default 'news'), "
        "count (int, default 5)"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query string",
            },
            "search_type": {
                "type": "string",
                "enum": ["news", "industry", "report"],
                "default": "news",
                "description": "Type of search to perform",
            },
            "count": {
                "type": "integer",
                "default": 5,
                "minimum": 1,
                "maximum": 20,
                "description": "Number of results to return",
            },
        },
        "required": ["query"],
    },
)


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.services.bocha_factory import build_bocha_service_from_env
    from app.tools.web_search import WebSearchArgs, WebSearchTool

    bocha = build_bocha_service_from_env()
    tool = WebSearchTool(bocha=bocha)
    validated = WebSearchArgs.model_validate(args)
    result = await tool.run(validated)
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
