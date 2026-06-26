"""MCP tool adapter — get_financial_statements (grouped dispatch).

把"财务三表"合并暴露为一个 MCP tool，内部按 `statement` 参数 dispatch 到
对应的 in-process Tool 类:
  - statement="balance"  → GetBalanceSheetTool
  - statement="cashflow" → GetCashflowTool
  - statement="income"   → GetFinancialsTool (income + financial indicators)

设计依据: Agent Harness Engineering Survey §4 — "prefer fewer, more expressive
tools over a large menu of narrow ones"; 同一主题的工具合并能降低 LLM 选择难度
+ 缩短工具描述上下文 + 提升 KV-cache 命中(论文 §5)。

Exports:
  TOOL_DEF  — mcp.types.Tool metadata
  handle()  — async dispatch function
"""

from __future__ import annotations

import json
from typing import Any

from mcp.types import TextContent, Tool

TOOL_DEF = Tool(
    name="get_financial_statements",
    description=(
        "Return the latest financial statement data for an A-share. "
        "statement='balance' returns balance-sheet items + solvency ratios; "
        "'cashflow' returns operating/investing/financing CF + positive_ocf signal; "
        "'income' returns revenue / net profit / ROE / P/E."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "ts_code": {
                "type": "string",
                "description": "A-share code, e.g. '600519.SH'",
            },
            "statement": {
                "type": "string",
                "enum": ["balance", "cashflow", "income"],
                "description": (
                    "Which statement to return: 'balance' (资产负债表), "
                    "'cashflow' (现金流量表), 'income' (利润表 + 财务指标)."
                ),
            },
            "end_date": {
                "type": "string",
                "description": "Optional period end date (YYYYMMDD).",
            },
            "period": {
                "type": "string",
                "enum": ["latest", "quarterly", "annual"],
                "default": "latest",
                "description": "Only applies to statement='income'.",
            },
        },
        "required": ["ts_code", "statement"],
    },
)


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.services.tushare_factory import build_tushare_service

    statement = args.get("statement")
    ts_code = args["ts_code"]
    end_date = args.get("end_date")
    tushare = build_tushare_service()

    if statement == "balance":
        from app.tools.get_balance_sheet import BalanceSheetArgs, GetBalanceSheetTool

        tool = GetBalanceSheetTool(tushare=tushare)
        validated = BalanceSheetArgs.model_validate({"ts_code": ts_code, "end_date": end_date})
        result = await tool.run(validated)
    elif statement == "cashflow":
        from app.tools.get_cashflow import CashflowArgs, GetCashflowTool

        tool = GetCashflowTool(tushare=tushare)  # type: ignore[assignment]
        validated = CashflowArgs.model_validate({"ts_code": ts_code, "end_date": end_date})
        result = await tool.run(validated)
    elif statement == "income":
        from app.tools.get_financials import FinancialsArgs, GetFinancialsTool

        tool = GetFinancialsTool(tushare=tushare)  # type: ignore[assignment]
        validated = FinancialsArgs.model_validate(
            {"ts_code": ts_code, "period": args.get("period", "latest"),
             "end_date": end_date}  # 传通期间末:问"2024年报"不再丢成"最新期"
        )
        result = await tool.run(validated)
    else:
        raise ValueError(
            f"invalid statement={statement!r}; must be one of: balance, cashflow, income"
        )

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
