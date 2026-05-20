"""MCP tool adapter — get_corporate_actions (grouped dispatch).

把"公司行为"类工具合并为一个 MCP tool，按 `action` 参数 dispatch:
  - action="forecast"        → GetForecastTool (业绩预告 + sentiment 信号)
  - action="dividend"        → GetDividendHistoryTool (分红记录 + consistency)
  - action="holder_change"   → GetHolderChangeTool (股东户数变化 + 集中度趋势)

Exports:
  TOOL_DEF  — mcp.types.Tool metadata
  handle()  — async dispatch function
"""

from __future__ import annotations

import json
from typing import Any

from mcp.types import TextContent, Tool

TOOL_DEF = Tool(
    name="get_corporate_actions",
    description=(
        "Return company-action history for an A-share. "
        "action='forecast' returns 业绩预告 + sentiment signal; "
        "'dividend' returns recent dividends + consistency score; "
        "'holder_change' returns 股东户数 trend + concentration label."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "ts_code": {
                "type": "string",
                "description": "A-share code, e.g. '600519.SH'",
            },
            "action": {
                "type": "string",
                "enum": ["forecast", "dividend", "holder_change"],
                "description": "Which corporate-action family to return.",
            },
            "period": {
                "type": "string",
                "description": "Only applies to action='forecast' (YYYYMMDD).",
            },
            "years_back": {
                "type": "integer",
                "description": (
                    "Lookback years. Applies to 'dividend' (default 5, 1-10) "
                    "and 'holder_change' (default 2, 1-5)."
                ),
            },
        },
        "required": ["ts_code", "action"],
    },
)


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.services.tushare_factory import build_tushare_service

    action = args.get("action")
    ts_code = args["ts_code"]
    tushare = build_tushare_service()

    if action == "forecast":
        from app.tools.get_forecast import ForecastArgs, GetForecastTool

        tool = GetForecastTool(tushare=tushare)
        validated = ForecastArgs.model_validate({"ts_code": ts_code, "period": args.get("period")})
        result = await tool.run(validated)
    elif action == "dividend":
        from app.tools.get_dividend_history import DividendHistoryArgs, GetDividendHistoryTool

        payload: dict[str, Any] = {"ts_code": ts_code}
        if "years_back" in args:
            payload["years_back"] = args["years_back"]
        tool = GetDividendHistoryTool(tushare=tushare)  # type: ignore[assignment]
        validated = DividendHistoryArgs.model_validate(payload)
        result = await tool.run(validated)
    elif action == "holder_change":
        from app.tools.get_holder_change import GetHolderChangeTool, HolderChangeArgs

        payload2: dict[str, Any] = {"ts_code": ts_code}
        if "years_back" in args:
            payload2["years_back"] = args["years_back"]
        tool = GetHolderChangeTool(tushare=tushare)  # type: ignore[assignment]
        validated = HolderChangeArgs.model_validate(payload2)
        result = await tool.run(validated)
    else:
        raise ValueError(
            f"invalid action={action!r}; must be one of: forecast, dividend, holder_change"
        )

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
