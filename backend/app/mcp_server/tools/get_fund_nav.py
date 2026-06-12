"""MCP tool adapter — get_fund_nav(基金类型与每日净值涨跌)。

Exports:
  TOOL_DEF  — mcp.types.Tool metadata(server.py list_tools 聚合)
  handle()  — async dispatch(server.py call_tool 聚合)
"""

from __future__ import annotations

import json
from typing import Any

from mcp.types import TextContent, Tool

TOOL_DEF = Tool(
    name="get_fund_nav",
    description="查基金类型与每日净值涨跌(场内ETF/场外基金)。组合里基金的涨跌用它。看不穿底层持仓。",
    inputSchema={
        "type": "object",
        "properties": {
            "ts_code": {"type": "string", "description": "基金代码,如 110011.OF"},
            "start_date": {"type": "string", "description": "YYYYMMDD"},
            "end_date": {"type": "string", "description": "YYYYMMDD"},
        },
        "required": ["ts_code", "start_date", "end_date"],
    },
)


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.tools.get_fund_nav import FundNavArgs, GetFundNavTool

    tool = GetFundNavTool()
    result = await tool.run(FundNavArgs.model_validate(args))
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
