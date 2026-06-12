"""GetIndexDailyTool — 指数日线与当日涨跌幅(沪深300 等)。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd
from pydantic import BaseModel

from app.tools.base import Tool

if TYPE_CHECKING:
    from app.services.tushare_service import TushareService


class IndexDailyArgs(BaseModel):
    ts_code: str  # 如 "000300.SH"(沪深300)
    start_date: str  # YYYYMMDD
    end_date: str


def _format_index_daily(df: pd.DataFrame, ts_code: str) -> dict[str, Any]:
    """DataFrame → 结构化 dict(纯函数,可单测,不碰网络/LLM)。"""
    if df is None or getattr(df, "empty", True):
        return {"ts_code": ts_code, "count": 0, "latest": None}
    df = df.sort_values("trade_date")
    last = df.iloc[-1]
    return {
        "ts_code": ts_code,
        "count": int(len(df)),
        "latest": {
            "trade_date": str(last["trade_date"]),
            "close": float(last["close"]),
            "pct_chg": float(last["pct_chg"]),
        },
        "series": {
            "dates": [str(d) for d in df["trade_date"]],
            "pct_chg": [float(x) for x in df["pct_chg"]],
        },
    }


class GetIndexDailyTool(Tool):
    name = "get_index_daily"
    description = "查指数日线与当日涨跌幅(如沪深300 000300.SH)。算组合'跟大盘'贡献时用。"
    args_schema = IndexDailyArgs

    def __init__(self, tushare: TushareService | None = None) -> None:
        if tushare is None:
            from app.services.tushare_factory import build_tushare_service

            tushare = build_tushare_service()
        self._tushare = tushare

    async def run(self, args: BaseModel) -> dict[str, Any]:
        a = IndexDailyArgs.model_validate(args.model_dump())
        df = await self._tushare.get_index_daily(
            ts_code=a.ts_code, start_date=a.start_date, end_date=a.end_date
        )
        return _format_index_daily(df, a.ts_code)
