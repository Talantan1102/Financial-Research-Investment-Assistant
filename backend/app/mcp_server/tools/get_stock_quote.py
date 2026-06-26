"""MCP tool adapter — get_stock_quote.

Wraps app.tools.get_stock_quote.StockQuoteTool.

Exports:
  TOOL_DEF  — mcp.types.Tool metadata for the list_tools aggregator in server.py
  handle()  — async dispatch function for the call_tool aggregator in server.py
"""

from __future__ import annotations

import json
from typing import Any

from mcp.types import TextContent, Tool

TOOL_DEF = Tool(
    name="get_stock_quote",
    description=("Return latest daily price for an A-share. Args: ts_code (str, e.g. '601398.SH')"),
    inputSchema={
        "type": "object",
        "properties": {
            "ts_code": {
                "type": "string",
                "description": "A-share code, e.g. '600519.SH'",
            },
        },
        "required": ["ts_code"],
    },
)


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.mcp_server._as_of import eval_as_of
    from app.services.tushare_factory import build_tushare_service
    from app.tools.get_stock_quote import StockQuoteArgs, StockQuoteTool

    tushare = build_tushare_service()
    tool = StockQuoteTool(tushare=tushare)
    payload = dict(args)
    _aso = eval_as_of()  # 评测钉基准日:透明截到 ≤as_of(模型不可见;inputSchema 仅 ts_code)
    if _aso:
        payload["as_of"] = _aso
    validated = StockQuoteArgs.model_validate(payload)
    result = await tool.run(validated)
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
