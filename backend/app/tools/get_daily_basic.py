"""GetDailyBasicTool — 估值/换手等日基础指标 (v0.8.5).

无派生字段, 直透 raw (PE/PB/PS/股息率/市值/换手率) — Analyst 后续用 PeHistoryTool
拿 percentile 作为派生信号.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from app.tools.base import Tool

if TYPE_CHECKING:
    from app.services.tushare_service import TushareService


class DailyBasicArgs(BaseModel):
    ts_code: str
    trade_date: str | None = None


class GetDailyBasicTool(Tool):
    """Return PE / PB / PS / dividend-yield / market-cap / turnover-rate snapshot."""

    name = "get_daily_basic"
    description = (
        "Return latest valuation snapshot (pe / pb / ps / dv_ratio / "
        "total_mv / circ_mv / turnover_rate) for an A-share."
    )
    args_schema = DailyBasicArgs

    def __init__(self, tushare: TushareService | None = None) -> None:
        if tushare is None:
            from app.services.tushare_factory import build_tushare_service

            tushare = build_tushare_service()
        self._tushare = tushare

    async def run(self, args: BaseModel) -> dict[str, Any]:
        a = DailyBasicArgs.model_validate(args.model_dump())
        df = await self._tushare.get_daily_basic(ts_code=a.ts_code, trade_date=a.trade_date)
        if df.empty:
            return {"ts_code": a.ts_code, "error": "no data"}
        row = df.iloc[0]
        return {
            "ts_code": a.ts_code,
            "trade_date": str(row.get("trade_date", "")),
            "pe": float(row.get("pe", 0.0) or 0.0),
            "pb": float(row.get("pb", 0.0) or 0.0),
            "ps": float(row.get("ps", 0.0) or 0.0),
            "dv_ratio": float(row.get("dv_ratio", 0.0) or 0.0),
            "total_mv": float(row.get("total_mv", 0.0) or 0.0),
            "circ_mv": float(row.get("circ_mv", 0.0) or 0.0),
            "turnover_rate": float(row.get("turnover_rate", 0.0) or 0.0),
        }
