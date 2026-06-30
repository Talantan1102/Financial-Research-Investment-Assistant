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
    as_of: str | None = None  # 评测钉基准日(verl tool_box 按此字段注入);给则覆盖 trade_date
    # 让 Path B(verl rollout)的快照与 gold 同钉到出题日,不随训练时间漂移。
    # Path A(MCP)走 handler 直接传 trade_date,不传 as_of,故此字段默认 None 不影响。


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
        trade_date = a.as_of or a.trade_date  # as_of(钉基准日)优先,与 gold 同期
        df = await self._tushare.get_daily_basic(ts_code=a.ts_code, trade_date=trade_date)
        if df.empty:
            return {"ts_code": a.ts_code, "error": "no data"}
        # Pick latest trade_date if multiple rows present (real Tushare may
        # return ascending series; mock returns 1 row so doesn't expose).
        if "trade_date" in df.columns and len(df) > 1:
            df = df.sort_values("trade_date", ascending=False)
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
