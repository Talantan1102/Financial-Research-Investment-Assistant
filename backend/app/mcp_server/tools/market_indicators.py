"""MCP tool adapter — get_market_indicators (grouped dispatch).

把"市场/估值/资金面"类工具合并为一个 MCP tool，按 `metric` 参数 dispatch:
  - metric="daily_basic"  → GetDailyBasicTool (PE/PB/PS/股息率/市值/换手率)
  - metric="pe_history"   → GetPeHistoryTool (PE 历史分位)
  - metric="money_flow"   → GetMoneyFlowTool (大单资金流 + 净流入信号)

Exports:
  TOOL_DEF  — mcp.types.Tool metadata
  handle()  — async dispatch function
"""

from __future__ import annotations

import json
from typing import Any

from mcp.types import TextContent, Tool

TOOL_DEF = Tool(
    name="get_market_indicators",
    description=(
        "Return market valuation / capital-flow indicators for an A-share. "
        "metric='daily_basic' returns PE/PB/PS/dividend-yield/market-cap/turnover snapshot; "
        "'pe_history' returns PE historical percentile + valuation band; "
        "'money_flow' returns large/medium-order buy & sell amounts + net_lg_signal."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "ts_code": {
                "type": "string",
                "description": "A-share code, e.g. '600519.SH'",
            },
            "metric": {
                "type": "string",
                "enum": ["daily_basic", "pe_history", "money_flow"],
                "description": "Which market-indicator family to return.",
            },
            "trade_date": {
                "type": "string",
                "description": "Only applies to metric='daily_basic' (YYYYMMDD).",
            },
            "years_back": {
                "type": "integer",
                "default": 5,
                "description": "Only applies to metric='pe_history' (lookback years).",
            },
            "current_pe": {
                "type": "number",
                "description": "Optional; only metric='pe_history' (override current PE).",
            },
            "start_date": {
                "type": "string",
                "description": "Only applies to metric='money_flow' (YYYYMMDD).",
            },
            "end_date": {
                "type": "string",
                "description": "Only applies to metric='money_flow' (YYYYMMDD).",
            },
        },
        "required": ["ts_code", "metric"],
    },
)


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.services.tushare_factory import build_tushare_service

    metric = args.get("metric")
    ts_code = args["ts_code"]
    tushare = build_tushare_service()

    if metric == "daily_basic":
        from app.tools.get_daily_basic import DailyBasicArgs, GetDailyBasicTool

        tool = GetDailyBasicTool(tushare=tushare)
        validated = DailyBasicArgs.model_validate(
            {"ts_code": ts_code, "trade_date": args.get("trade_date")}
        )
        result = await tool.run(validated)
    elif metric == "pe_history":
        from app.tools.get_pe_history import GetPeHistoryTool, PeHistoryArgs

        tool = GetPeHistoryTool(tushare=tushare)  # type: ignore[assignment]
        payload: dict[str, Any] = {
            "ts_code": ts_code,
            "years_back": args.get("years_back", 5),
        }
        if "current_pe" in args:
            payload["current_pe"] = args["current_pe"]
        validated = PeHistoryArgs.model_validate(payload)
        result = await tool.run(validated)
    elif metric == "money_flow":
        from app.tools.get_money_flow import GetMoneyFlowTool, MoneyFlowArgs

        if "start_date" not in args or "end_date" not in args:
            raise ValueError("metric='money_flow' requires start_date and end_date")
        tool = GetMoneyFlowTool(tushare=tushare)  # type: ignore[assignment]
        validated = MoneyFlowArgs.model_validate(
            {
                "ts_code": ts_code,
                "start_date": args["start_date"],
                "end_date": args["end_date"],
            }
        )
        result = await tool.run(validated)
    else:
        raise ValueError(
            f"invalid metric={metric!r}; must be one of: daily_basic, pe_history, money_flow"
        )

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
