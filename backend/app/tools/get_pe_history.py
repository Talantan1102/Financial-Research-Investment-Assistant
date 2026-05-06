"""GetPeHistoryTool — PE 历史分位 + 派生估值带 (v0.8.5)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from app.tools.base import Tool

if TYPE_CHECKING:
    from app.services.tushare_service import TushareService


class PeHistoryArgs(BaseModel):
    ts_code: str
    years_back: int = Field(default=5, ge=1, le=10)


ValuationBand = Literal["低估", "合理", "高估"]


def _classify_valuation_band(percentile: float) -> ValuationBand:
    """0-0.3 → 低估; 0.3-0.7 → 合理; 0.7-1.0 → 高估."""
    if percentile < 0.3:
        return "低估"
    if percentile < 0.7:
        return "合理"
    return "高估"


class GetPeHistoryTool(Tool):
    """Return PE percentile vs N-year history + derived valuation band.

    Derived field:
      - valuation_band: '低估' (<30%) / '合理' (30-70%) / '高估' (>=70%).
    """

    name = "get_pe_history"
    description = (
        "Return current_pe + historical_percentile + min/max/median PE over the "
        "past N years and a derived valuation_band (低估/合理/高估)."
    )
    args_schema = PeHistoryArgs

    def __init__(self, tushare: TushareService | None = None) -> None:
        if tushare is None:
            from app.services.tushare_factory import build_tushare_service

            tushare = build_tushare_service()
        self._tushare = tushare

    async def run(self, args: BaseModel) -> dict[str, Any]:
        a = PeHistoryArgs.model_validate(args.model_dump())
        df = await self._tushare.get_pe_history(ts_code=a.ts_code, years_back=a.years_back)
        if df.empty:
            return {"ts_code": a.ts_code, "error": "no data"}
        # aggregation result, single row by design — no sort needed
        # (RealTushareService.get_pe_history 自己构造 1 行 df, 含分位/min/max/median)
        row = df.iloc[0]
        percentile = float(row.get("historical_percentile", 0.0) or 0.0)
        return {
            "ts_code": a.ts_code,
            "current_pe": float(row.get("current_pe", 0.0) or 0.0),
            "historical_percentile": percentile,
            "min_pe": float(row.get("min_pe", 0.0) or 0.0),
            "max_pe": float(row.get("max_pe", 0.0) or 0.0),
            "median_pe": float(row.get("median_pe", 0.0) or 0.0),
            "valuation_band": _classify_valuation_band(percentile),
        }
