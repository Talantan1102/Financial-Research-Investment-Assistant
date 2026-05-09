"""MCP tool adapter — kb_search.

Wraps app.tools.kb_search.KbSearchTool (Milvus-based).

Exports:
  TOOL_DEF  — mcp.types.Tool metadata for the list_tools aggregator in server.py
  handle()  — async dispatch function for the call_tool aggregator in server.py
"""

from __future__ import annotations

import json
from typing import Any

from mcp.types import TextContent, Tool

TOOL_DEF = Tool(
    name="kb_search",
    description=(
        "Search internal knowledge base (research reports / financial statements / policy documents). "
        "Args: query (str), top_k (int, default 5)"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Semantic search query",
            },
            "top_k": {
                "type": "integer",
                "default": 5,
                "minimum": 1,
                "maximum": 20,
                "description": "Maximum number of results to return",
            },
        },
        "required": ["query"],
    },
)


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.services.kb_factory import build_kb_search_service_from_env
    from app.tools.kb_search import KbSearchArgs, KbSearchTool

    kb_service = build_kb_search_service_from_env()
    tool = KbSearchTool(kb_service=kb_service)
    validated = KbSearchArgs.model_validate(args)
    result = await tool.run(validated)
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
