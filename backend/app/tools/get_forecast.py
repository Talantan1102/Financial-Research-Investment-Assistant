"""GetForecastTool — 业绩预告 + 派生情绪信号 (v0.8.5)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

from app.tools.base import Tool

if TYPE_CHECKING:
    from app.services.tushare_service import TushareService


class ForecastArgs(BaseModel):
    ts_code: str
    period: str | None = None


ForecastSignal = Literal["positive", "neutral", "negative"]

_POSITIVE_KEYWORDS = ("预增", "扭亏", "略增", "续盈")
_NEGATIVE_KEYWORDS = ("预减", "首亏", "续亏", "略减")


def _classify_forecast_signal(forecast_type: str) -> ForecastSignal:
    """业绩预告 type → 情绪信号."""
    if not forecast_type:
        return "neutral"
    for kw in _POSITIVE_KEYWORDS:
        if kw in forecast_type:
            return "positive"
    for kw in _NEGATIVE_KEYWORDS:
        if kw in forecast_type:
            return "negative"
    return "neutral"


class GetForecastTool(Tool):
    """Return latest earnings forecast + derived sentiment signal.

    Derived field:
      - signal: 'positive' (预增/扭亏/略增/续盈) /
                'negative' (预减/首亏/续亏/略减) /
                'neutral' (other).
    """

    name = "get_forecast"
    description = (
        "Return earnings-forecast type, p_change_min/max and a derived "
        "signal (positive/neutral/negative) for an A-share."
    )
    args_schema = ForecastArgs

    def __init__(self, tushare: TushareService | None = None) -> None:
        if tushare is None:
            from app.services.tushare_factory import build_tushare_service

            tushare = build_tushare_service()
        self._tushare = tushare

    async def run(self, args: BaseModel) -> dict[str, Any]:
        a = ForecastArgs.model_validate(args.model_dump())
        df = await self._tushare.get_forecast(ts_code=a.ts_code, period=a.period)
        if df.empty:
            return {"ts_code": a.ts_code, "error": "no data"}
        row = df.iloc[0]
        forecast_type = str(row.get("type", "") or "")
        return {
            "ts_code": a.ts_code,
            "period": str(row.get("period", "")),
            "type": forecast_type,
            "p_change_min": float(row.get("p_change_min", 0.0) or 0.0),
            "p_change_max": float(row.get("p_change_max", 0.0) or 0.0),
            "signal": _classify_forecast_signal(forecast_type),
        }
