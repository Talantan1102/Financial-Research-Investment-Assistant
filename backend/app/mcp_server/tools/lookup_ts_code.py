"""MCP tool adapter — lookup_ts_code(股票名 → ts_code）。

填 Path A 工具面缺口:数据/估值/财报工具都要 ts_code,但题面给的是公司简称。
没有它,模型只能靠参数记忆"背"代码——强模型背得对,弱模型(8B)背错 → 查错股票必失败
(见 memory sft-eval-null-result-diagnosis)。薄包 app.tools.LookupTsCodeTool(同一份逻辑,
底层 TushareService.get_stock_basic 精确名匹配)。

Exports:
  TOOL_DEF  — mcp.types.Tool metadata
  handle()  — async dispatch function
"""

from __future__ import annotations

import json
from typing import Any

from mcp.types import TextContent, Tool

TOOL_DEF = Tool(
    name="lookup_ts_code",
    description=(
        "Resolve an A-share company name to its ts_code (e.g. '贵州茅台' → '600519.SH'). "
        "ALWAYS call this FIRST to get the ts_code before any data/financial/valuation "
        "tool — do NOT guess or recall the code from memory, wrong codes return wrong data."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "A-share company short name, e.g. '神州泰岳'.",
            },
        },
        "required": ["name"],
    },
)


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.services.tushare_factory import build_tushare_service
    from app.tools.lookup_ts_code import LookupTsCodeArgs, LookupTsCodeTool

    tool = LookupTsCodeTool(tushare=build_tushare_service())
    validated = LookupTsCodeArgs.model_validate({"name": args["name"]})
    result = await tool.run(validated)
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
