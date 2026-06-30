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
        "Return financial statement data for an A-share. "
        "statement='balance' returns balance-sheet items + solvency ratios; "
        "'cashflow' returns operating/investing/financing CF + positive_ocf signal; "
        "'income' returns revenue, net_profit, roe, gross_margin (销售毛利率 %), "
        "debt_to_assets (资产负债率 %), eps (每股收益 元/股), bps (每股净资产 元/股), "
        "revenue_yoy / net_profit_yoy (营收/净利同比 %). "
        "(For a specific fiscal year pass end_date, e.g. 20241231 = FY2024 annual.)"
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
                "description": (
                    "Period end date (YYYYMMDD). IMPORTANT: when the question asks "
                    "about a SPECIFIC fiscal year (e.g. '2024年报'/'2024年净利润'), you "
                    "MUST pass that year's end_date (annual report → YYYY1231, e.g. "
                    "'20241231'). If omitted, you get the MOST RECENT period, which may "
                    "be a LATER year than the question asks and give a wrong answer."
                ),
            },
            "period": {
                "type": "string",
                "enum": ["latest", "quarterly", "annual"],
                "default": "latest",
                "description": (
                    "Only applies to statement='income'. 'annual' = a full-year report "
                    "(pair with end_date=YYYY1231 to pin the exact year; without "
                    "end_date it returns the latest available annual report)."
                ),
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
            {
                "ts_code": ts_code,
                "period": args.get("period", "latest"),
                "end_date": end_date,
            }  # 传通期间末:问"2024年报"不再丢成"最新期"
        )
        result = await tool.run(validated)
    else:
        raise ValueError(
            f"invalid statement={statement!r}; must be one of: balance, cashflow, income"
        )

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
