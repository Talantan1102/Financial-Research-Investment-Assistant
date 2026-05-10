"""MCP tool adapter — get_news.

Wraps app.tools.get_news.GetNewsTool (Bocha-based).

Exports:
  TOOL_DEF  — mcp.types.Tool metadata for the list_tools aggregator in server.py
  handle()  — async dispatch function for the call_tool aggregator in server.py
"""

from __future__ import annotations

import json
from typing import Any

from mcp.types import TextContent, Tool

TOOL_DEF = Tool(
    name="get_news",
    description=(
        "Fetch recent financial news via Bocha search. "
        "Args: ts_code (str | null), n (int, default 5), days_back (int, default 7)"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "ts_code": {
                "type": ["string", "null"],
                "description": "A-share code to filter news, or null for market-wide news",
            },
            "n": {
                "type": "integer",
                "default": 5,
                "minimum": 1,
                "maximum": 20,
                "description": "Number of news items to return",
            },
            "days_back": {
                "type": "integer",
                "default": 7,
                "minimum": 1,
                "maximum": 90,
                "description": "How many days back to search",
            },
        },
        "required": [],
    },
)


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.services.bocha_factory import build_bocha_service_from_env
    from app.tools.get_news import GetNewsTool, NewsArgs

    bocha = build_bocha_service_from_env()
    tool = GetNewsTool(bocha=bocha)
    validated = NewsArgs.model_validate(args)
    result = await tool.run(validated)
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
