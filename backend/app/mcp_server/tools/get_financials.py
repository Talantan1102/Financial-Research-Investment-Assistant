"""MCP tool adapter — get_financials.

Wraps app.tools.get_financials.GetFinancialsTool.

Exports:
  TOOL_DEF  — mcp.types.Tool metadata for the list_tools aggregator in server.py
  handle()  — async dispatch function for the call_tool aggregator in server.py
"""

from __future__ import annotations

import json
from typing import Any

from mcp.types import TextContent, Tool

TOOL_DEF = Tool(
    name="get_financials",
    description=(
        "Return key financial metrics (revenue, net profit, ROE, P/E) for an A-share. "
        "Args: ts_code (str), period ('latest' | 'quarterly' | 'annual', default 'latest')"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "ts_code": {
                "type": "string",
                "description": "A-share code, e.g. '600519.SH'",
            },
            "period": {
                "type": "string",
                "enum": ["latest", "quarterly", "annual"],
                "default": "latest",
                "description": "Reporting period granularity",
            },
        },
        "required": ["ts_code"],
    },
)


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.services.tushare_factory import build_tushare_service
    from app.tools.get_financials import FinancialsArgs, GetFinancialsTool

    tushare = build_tushare_service()
    tool = GetFinancialsTool(tushare=tushare)
    validated = FinancialsArgs.model_validate(args)
    result = await tool.run(validated)
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
