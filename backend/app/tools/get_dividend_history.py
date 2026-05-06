"""GetDividendHistoryTool — 分红历史 + 派生连续性指标 (v0.8.5)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from app.tools.base import Tool

if TYPE_CHECKING:
    from app.services.tushare_service import TushareService


class DividendHistoryArgs(BaseModel):
    ts_code: str
    years_back: int = Field(default=5, ge=1, le=10)


class GetDividendHistoryTool(Tool):
    """Return recent dividend records + derived consistency score.

    Derived field:
      - dividend_consistency: float in [0, 1] — fraction of past years with
        a non-zero cash dividend. 5/5 ≈ 1.0 means consistent payer.
    """

    name = "get_dividend_history"
    description = (
        "Return recent_dividends (list of {ann_date, cash_div}), avg_dv_ratio_5y "
        "and derived dividend_consistency (0-1) for an A-share."
    )
    args_schema = DividendHistoryArgs

    def __init__(self, tushare: TushareService | None = None) -> None:
        if tushare is None:
            from app.services.tushare_factory import build_tushare_service

            tushare = build_tushare_service()
        self._tushare = tushare

    async def run(self, args: BaseModel) -> dict[str, Any]:
        a = DividendHistoryArgs.model_validate(args.model_dump())
        df = await self._tushare.get_dividend_history(ts_code=a.ts_code, years_back=a.years_back)
        if df.empty:
            return {"ts_code": a.ts_code, "error": "no data"}
        # Sort by ann_date desc so recent_dividends 列表语义稳定 (latest first).
        # Real Tushare 顺序不保证 — mock 已 desc 但 production 可能 asc.
        # consistency 数学 order-independent, 但列表语义会翻转.
        if "ann_date" in df.columns:
            df = df.sort_values("ann_date", ascending=False)
        # Compact recent_dividends list (latest N rows)
        recent: list[dict[str, Any]] = []
        cash_divs: list[float] = []
        for _, row in df.iterrows():
            cd = float(row.get("cash_div", 0.0) or 0.0)
            recent.append(
                {
                    "ann_date": str(row.get("ann_date", "")),
                    "cash_div": cd,
                }
            )
            cash_divs.append(cd)
        non_zero_years = sum(1 for cd in cash_divs if cd > 0)
        consistency = non_zero_years / max(len(cash_divs), 1)
        avg_dv = sum(cash_divs) / max(len(cash_divs), 1)
        return {
            "ts_code": a.ts_code,
            "recent_dividends": recent,
            "avg_dv_ratio_5y": avg_dv,
            "dividend_consistency": consistency,
        }
