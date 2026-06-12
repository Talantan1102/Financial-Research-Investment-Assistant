"""MCP tool adapter — get_index_daily(指数日线与当日涨跌幅,沪深300 等)。

Exports:
  TOOL_DEF  — mcp.types.Tool metadata(server.py list_tools 聚合)
  handle()  — async dispatch(server.py call_tool 聚合)
"""

from __future__ import annotations

import json
from typing import Any

from mcp.types import TextContent, Tool

TOOL_DEF = Tool(
    name="get_index_daily",
    description="查指数日线与当日涨跌幅(沪深300=000300.SH,上证=000001.SH 等)。",
    inputSchema={
        "type": "object",
        "properties": {
            "ts_code": {"type": "string", "description": "指数代码,如 000300.SH"},
            "start_date": {"type": "string", "description": "YYYYMMDD"},
            "end_date": {"type": "string", "description": "YYYYMMDD"},
        },
        "required": ["ts_code", "start_date", "end_date"],
    },
)


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.tools.get_index_daily import GetIndexDailyTool, IndexDailyArgs
    tool = GetIndexDailyTool()
    result = await tool.run(IndexDailyArgs.model_validate(args))
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
