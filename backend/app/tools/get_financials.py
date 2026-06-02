"""Tool: get_financials — key income-statement + financial-indicator metrics."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

from app.tools.base import Tool, ToolError

if TYPE_CHECKING:
    from app.services.tushare_service import TushareService


class FinancialsArgs(BaseModel):
    ts_code: str
    period: Literal["latest", "quarterly", "annual"] = "latest"


class GetFinancialsTool(Tool):
    """Return key financial metrics for a given A-share.

    Data source: TushareService.get_income (profit / loss statement)
    and TushareService.get_fina_indicator (financial ratios).
    Both methods take an optional end_date; we default to the latest period
    (20241231) regardless of the `period` arg—the mock always returns one
    synthetic period per query, so "latest" / "quarterly" / "annual" are
    semantically equivalent at this mock tier.
    """

    name = "get_financials"
    description = (
        "Return revenue, net profit, and ROE for a given A-share "
        "(ts_code). period: 'latest' | 'quarterly' | 'annual'. "
        "Note: pe is always 0.0; use get_daily_basic for P/E data."
    )
    args_schema = FinancialsArgs

    def __init__(self, tushare: TushareService) -> None:
        self._tushare = tushare

    async def run(self, args: BaseModel) -> dict[str, Any]:
        validated = FinancialsArgs.model_validate(args.model_dump())

        try:
            income_df = await self._tushare.get_income(ts_code=validated.ts_code)
            fina_df = await self._tushare.get_fina_indicator(ts_code=validated.ts_code)
        except Exception as exc:
            raise ToolError(f"TushareService call failed: {exc}") from exc

        # Extract most recent income row
        revenue: float = 0.0
        net_profit: float = 0.0
        if not income_df.empty:
            row = income_df.sort_values("end_date", ascending=False).iloc[0]
            revenue = float(row.get("total_revenue", 0.0) or 0.0)
            net_profit = float(row.get("n_income_attr_p", 0.0) or 0.0)

        # C55: read the correct fina_indicator columns.
        # Previously: 'roe' was read from netprofit_margin (mislabeled) and 'pe' from eps (wrong).
        # Fix: roe → fi_row['roe'] (tushare fina_indicator includes roe in both real and mock paths).
        #      pe_ttm is NOT in fina_indicator; set pe=0.0 until sourced from daily_basic separately.
        roe: float = 0.0
        pe: float = 0.0
        if not fina_df.empty:
            fi_row = fina_df.sort_values("end_date", ascending=False).iloc[0]
            roe = float(fi_row.get("roe", 0.0) or 0.0)
            # pe_ttm is not in fina_indicator — callers should source it from get_daily_basic.
            pe = 0.0

        return {
            "ts_code": validated.ts_code,
            "period": validated.period,
            "revenue": revenue,
            "net_profit": net_profit,
            "roe": roe,
            "pe": pe,
        }
