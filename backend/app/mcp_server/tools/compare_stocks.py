"""MCP tool adapter — compare_stocks (NEW composite tool).

No in-process equivalent: aggregates get_stock_quote + get_financials for 2-5
stocks in parallel via asyncio.gather, returns a unified comparison payload.

Exports:
  TOOL_DEF  — mcp.types.Tool metadata for the list_tools aggregator in server.py
  handle()  — async dispatch function for the call_tool aggregator in server.py
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp.types import TextContent, Tool

TOOL_DEF = Tool(
    name="compare_stocks",
    description=(
        "Compare 2-5 A-shares side-by-side: fetches latest quote + financials for each "
        "in parallel and returns a unified comparison list. "
        "Args: ts_codes (list[str], 2-5 elements)"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "ts_codes": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 5,
                "description": "List of 2-5 A-share codes, e.g. ['600519.SH', '601398.SH']",
            },
        },
        "required": ["ts_codes"],
    },
)


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.services.tushare_factory import build_tushare_service
    from app.tools.get_financials import FinancialsArgs, GetFinancialsTool
    from app.tools.get_stock_quote import StockQuoteArgs, StockQuoteTool

    ts_codes: list[str] = args["ts_codes"]

    tushare = build_tushare_service()
    quote_tool = StockQuoteTool(tushare=tushare)
    fin_tool = GetFinancialsTool(tushare=tushare)

    async def _row(ts: str) -> dict[str, Any]:
        quote_result, fin_result = await asyncio.gather(
            quote_tool.run(StockQuoteArgs(ts_code=ts)),
            fin_tool.run(FinancialsArgs(ts_code=ts, period="latest")),
        )
        return {"ts_code": ts, "quote": quote_result, "financials": fin_result}

    rows = await asyncio.gather(*[_row(t) for t in ts_codes])
    payload = {"comparison": list(rows)}
    return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]
