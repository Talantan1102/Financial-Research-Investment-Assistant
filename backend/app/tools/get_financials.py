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
        "Return revenue, net profit, ROE, and P/E for a given A-share "
        "(ts_code). period: 'latest' | 'quarterly' | 'annual'."
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

        # Extract financial ratios — ROE / PE 不在 fina_indicator 列里,只暴露真实有
        # 的指标(net_profit_margin / eps),避免下游 LLM 把净利率读成 ROE、EPS 读成 PE。
        net_profit_margin: float = 0.0
        eps: float = 0.0
        if not fina_df.empty:
            fi_row = fina_df.sort_values("end_date", ascending=False).iloc[0]
            net_profit_margin = float(fi_row.get("netprofit_margin", 0.0) or 0.0)
            eps = float(fi_row.get("eps", 0.0) or 0.0)

        return {
            "ts_code": validated.ts_code,
            "period": validated.period,
            "revenue": revenue,
            "net_profit": net_profit,
            "net_profit_margin": net_profit_margin,
            "eps": eps,
        }
