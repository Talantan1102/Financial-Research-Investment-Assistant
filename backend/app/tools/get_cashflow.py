"""GetCashflowTool — 现金流量表 + 派生 OCF 信号 (v0.8.5)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from app.tools.base import Tool

if TYPE_CHECKING:
    from app.services.tushare_service import TushareService


class CashflowArgs(BaseModel):
    ts_code: str
    end_date: str | None = None


class GetCashflowTool(Tool):
    """Return cashflow-statement key items + derived OCF signal.

    Derived field (computed in Python so the LLM consumes structured signals):
      - positive_ocf: bool — whether operating-activity cash flow is positive.

    Note: a "true" ocf_to_net_income ratio would require the income statement's
    net_income, which is on a separate Tushare endpoint. To keep this tool
    pure (single-API, deterministic under LLM_MODE=none) we expose a coarser
    boolean signal instead. The Analyst can cross-reference get_financials.

    TODO(Task 5): cashflow_quality.md methodology 应明示 Analyst —
    真 OCF/NI 比率 = GetCashflowTool.n_cashflow_act / GetFinancialsTool.net_profit
    (本 tool 派生只给 positive_ocf binary signal, 完整比率需 Analyst 跨 tool 算).
    """

    name = "get_cashflow"
    description = (
        "Return n_cashflow_act (operating CF), n_cashflow_inv_act (investing CF), "
        "n_cash_flows_fnc_act (financing CF) and derived positive_ocf signal."
    )
    args_schema = CashflowArgs

    def __init__(self, tushare: TushareService | None = None) -> None:
        if tushare is None:
            from app.services.tushare_factory import build_tushare_service

            tushare = build_tushare_service()
        self._tushare = tushare

    async def run(self, args: BaseModel) -> dict[str, Any]:
        a = CashflowArgs.model_validate(args.model_dump())
        df = await self._tushare.get_cashflow(ts_code=a.ts_code, end_date=a.end_date)
        if df.empty:
            return {"ts_code": a.ts_code, "error": "no data"}
        if "end_date" in df.columns and len(df) > 1:
            df = df.sort_values("end_date", ascending=False)
        row = df.iloc[0]
        n_cashflow_act = float(row.get("n_cashflow_act", 0.0) or 0.0)
        return {
            "ts_code": a.ts_code,
            "end_date": str(row.get("end_date", "")),
            "n_cashflow_act": n_cashflow_act,
            "n_cashflow_inv_act": float(row.get("n_cashflow_inv_act", 0.0) or 0.0),
            "n_cash_flows_fnc_act": float(row.get("n_cash_flows_fnc_act", 0.0) or 0.0),
            "positive_ocf": n_cashflow_act > 0,
        }
