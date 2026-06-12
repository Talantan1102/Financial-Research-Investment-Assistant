"""GetFundNavTool — 基金类型与每日净值涨跌(场内/场外基金)。

注:"看不穿底层" — 本工具只取净值层面涨跌,不穿透基金底层持仓。
基金底层持仓只到季报、滞后,所以看不穿。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd
from pydantic import BaseModel

from app.tools.base import Tool

if TYPE_CHECKING:
    from app.services.tushare_service import TushareService


class FundNavArgs(BaseModel):
    ts_code: str  # 如 "110011.OF"
    start_date: str  # YYYYMMDD
    end_date: str


def _format_fund_nav(
    nav: pd.DataFrame,
    ts_code: str,
    fund_type: str | None,
    fund_name: str | None,
) -> dict[str, Any]:
    """DataFrame → 结构化 dict(纯函数,可单测,不碰网络/LLM)。"""
    if nav is None or getattr(nav, "empty", True):
        return {"ts_code": ts_code, "fund_type": fund_type, "fund_name": fund_name, "latest": None}
    nav = nav.sort_values("nav_date")
    last = float(nav.iloc[-1]["unit_nav"])
    prev = float(nav.iloc[-2]["unit_nav"]) if len(nav) >= 2 else last
    pct = round((last - prev) / prev * 100, 4) if prev else 0.0
    return {
        "ts_code": ts_code,
        "fund_type": fund_type,
        "fund_name": fund_name,
        "latest": {
            "nav_date": str(nav.iloc[-1]["nav_date"]),
            "unit_nav": last,
            "pct_chg": pct,
        },
        "as_of_note": "基金底层持仓只到季报、滞后,本工具只取净值层面涨跌,不穿透底层。",
    }


class GetFundNavTool(Tool):
    name = "get_fund_nav"
    description = (
        "查基金类型与每日净值涨跌(场内/场外基金)。组合里基金部分的涨跌用它。看不穿底层持仓。"
    )
    args_schema = FundNavArgs

    def __init__(self, tushare: TushareService | None = None) -> None:
        if tushare is None:
            from app.services.tushare_factory import build_tushare_service

            tushare = build_tushare_service()
        self._tushare = tushare

    async def run(self, args: BaseModel) -> dict[str, Any]:
        a = FundNavArgs.model_validate(args.model_dump())
        basic = await self._tushare.get_fund_basic(ts_code=a.ts_code)
        ftype = str(basic.iloc[0]["fund_type"]) if basic is not None and not basic.empty else None
        fname = str(basic.iloc[0]["name"]) if basic is not None and not basic.empty else None
        nav = await self._tushare.get_fund_nav(
            ts_code=a.ts_code, start_date=a.start_date, end_date=a.end_date
        )
        return _format_fund_nav(nav, a.ts_code, ftype, fname)
