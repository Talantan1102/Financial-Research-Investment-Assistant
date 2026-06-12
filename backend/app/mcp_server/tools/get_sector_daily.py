"""MCP tool adapter — get_sector_daily(个股行业归属 + 板块当日涨跌)。

Exports:
  TOOL_DEF  — mcp.types.Tool metadata(server.py list_tools 聚合)
  handle()  — async dispatch(server.py call_tool 聚合)
"""

from __future__ import annotations

import json
from typing import Any

from mcp.types import TextContent, Tool

TOOL_DEF = Tool(
    name="get_sector_daily",
    description="查个股所属申万行业 + 该板块当日涨跌幅。持仓监控看板块表现时用。",
    inputSchema={
        "type": "object",
        "properties": {
            "ts_code": {"type": "string", "description": "个股代码,如 600519.SH"},
            "trade_date": {"type": "string", "description": "YYYYMMDD,查询当日"},
        },
        "required": ["ts_code", "trade_date"],
    },
)


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.tools.get_sector_daily import GetSectorDailyTool, SectorDailyArgs

    tool = GetSectorDailyTool()
    result = await tool.run(SectorDailyArgs.model_validate(args))
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
