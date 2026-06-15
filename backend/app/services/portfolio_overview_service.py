"""portfolio_overview_service — 聚合服务:取数 + 拆账 + 看结构。

build_overview(session, *, user_id) -> dict
  1. 读持仓(PositionService)
  2. 对每只持仓按 asset_class 取当日涨跌
     - stock: get_index_daily(沪深300) 取市场涨跌 + get_sector_daily 取板块;
              MVP: 个股当日涨跌用其板块涨跌近似(beta≈1),不调 get_daily
     - fund_otc / fund_etf: get_fund_nav 取净值涨跌
     - bond / gold / cash: today_pct = 0.0 (兜底)
  3. compute_daily_attribution -> AttributionResult
  4. 看结构: by_class 市值占比, by_sector 股票板块市值占比, as_of 占位
  5. 返回 dict {attribution, structure, total_value, today_pct}
"""

from __future__ import annotations

import dataclasses
import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services.portfolio_analytics import HoldingDaily, compute_daily_attribution
from app.services.position_service import PositionService
from app.services.tushare_factory import build_tushare_service


def _today_str() -> str:
    return datetime.date.today().strftime("%Y%m%d")


def _lookback_str(days: int = 5) -> str:
    """往前推 N 个自然日作为 start_date,保证取到最近两个交易日数据。"""
    d = datetime.date.today() - datetime.timedelta(days=days)
    return d.strftime("%Y%m%d")


async def _get_market_pct(tushare: Any, trade_date_end: str) -> float | None:
    """取沪深300当日涨跌幅,失败返回 None。"""
    try:
        df = await tushare.get_index_daily(
            ts_code="000300.SH",
            start_date=_lookback_str(10),
            end_date=trade_date_end,
        )
        if df is None or getattr(df, "empty", True):
            return None
        df = df.sort_values("trade_date")
        return float(df.iloc[-1]["pct_chg"])
    except Exception:
        return None


async def _get_sector_info(
    tushare: Any, ts_code: str, trade_date: str
) -> tuple[str | None, float | None]:
    """取个股行业名 + 板块当日涨跌幅。返回 (sector_name, sector_pct)。"""
    try:
        basic = await tushare.get_stock_basic(ts_code=ts_code)
        if basic is None or getattr(basic, "empty", True):
            return None, None
        industry = str(basic.iloc[0]["industry"])

        from app.tools.get_sector_daily import _INDUSTRY_TO_SW

        index_code = _INDUSTRY_TO_SW.get(industry)
        if index_code is None:
            return industry, None

        df = await tushare.get_sw_index_daily(index_code=index_code, trade_date=trade_date)
        if df is None or getattr(df, "empty", True):
            return industry, None

        # 申万 sw_daily 涨跌幅列名是 pct_change(不是 pct_chg)
        col = "pct_change" if "pct_change" in df.columns else "pct_chg"
        return industry, float(df.iloc[0][col])
    except Exception:
        return None, None


async def _get_fund_pct(tushare: Any, ts_code: str, trade_date_end: str) -> float:
    """取基金净值当日涨跌幅;失败返回 0.0。"""
    try:
        nav = await tushare.get_fund_nav(
            ts_code=ts_code,
            start_date=_lookback_str(10),
            end_date=trade_date_end,
        )
        if nav is None or getattr(nav, "empty", True):
            return 0.0
        nav = nav.sort_values("nav_date")
        if "pct_chg" in nav.columns:
            return float(nav.iloc[-1]["pct_chg"])
        # 手算
        if len(nav) >= 2:
            last = float(nav.iloc[-1]["unit_nav"])
            prev = float(nav.iloc[-2]["unit_nav"])
            if prev > 0:
                return round((last / prev - 1.0) * 100, 4)
        return 0.0
    except Exception:
        return 0.0


async def build_overview(session: Session, *, user_id: object) -> dict:
    """聚合服务入口。返回 attribution / structure / total_value / today_pct。"""
    tushare = build_tushare_service()
    trade_date_end = _today_str()

    # 1. 读持仓
    positions = PositionService(session).list_for_user(user_id)  # type: ignore[arg-type]

    if not positions:
        empty_result = compute_daily_attribution([])
        return {
            "attribution": dataclasses.asdict(empty_result),
            "structure": {"by_class": {}, "by_sector": {}, "as_of": None},
            "total_value": 0.0,
            "today_pct": 0.0,
        }

    # 2. 取大盘涨跌(所有股票共用,只调一次)
    market_pct = await _get_market_pct(tushare, trade_date_end)

    holdings: list[HoldingDaily] = []

    for pos in positions:
        qty = float(pos.quantity)
        price = (
            float(pos.last_quote_price) if pos.last_quote_price is not None else float(pos.avg_cost)
        )
        market_value = qty * price
        if market_value <= 0:
            continue

        ac = str(pos.asset_class) if pos.asset_class else "stock"
        ts_code = str(pos.ts_code)

        if ac == "stock":
            sector_name, sector_pct = await _get_sector_info(tushare, ts_code, trade_date_end)
            # MVP: 个股当日涨跌用其板块涨跌近似(beta≈1),不调 get_daily(mock 端 LLM 背书、慢);real 端可后续接真 get_daily
            today_pct = sector_pct if sector_pct is not None else 0.0
            holdings.append(
                HoldingDaily(
                    ts_code=ts_code,
                    asset_class=ac,
                    market_value=market_value,
                    today_pct=today_pct,
                    sector=sector_name,
                    sector_pct=sector_pct,
                    market_pct=market_pct,
                )
            )

        elif ac in ("fund_otc", "fund_etf"):
            today_pct = await _get_fund_pct(tushare, ts_code, trade_date_end)
            holdings.append(
                HoldingDaily(
                    ts_code=ts_code,
                    asset_class=ac,
                    market_value=market_value,
                    today_pct=today_pct,
                )
            )

        else:
            # bond / gold / cash 等 — today_pct = 0.0, 不拆板块
            holdings.append(
                HoldingDaily(
                    ts_code=ts_code,
                    asset_class=ac,
                    market_value=market_value,
                    today_pct=0.0,
                )
            )

    # 3. 拆账
    attribution = compute_daily_attribution(holdings)

    # 4. 看结构
    total_mv = sum(h.market_value for h in holdings)

    by_class: dict[str, float] = {}
    by_sector: dict[str, float] = {}

    if total_mv > 0:
        for h in holdings:
            ratio = h.market_value / total_mv
            by_class[h.asset_class] = round(by_class.get(h.asset_class, 0.0) + ratio, 6)
            if h.asset_class == "stock" and h.sector:
                by_sector[h.sector] = round(by_sector.get(h.sector, 0.0) + ratio, 6)

    # as_of: 基金季报披露日占位,实际业务需接基金底层数据,此处标注说明
    as_of: str | None = "季报日未接入(基金底层持仓滞后,本版本不穿透)"

    return {
        "attribution": dataclasses.asdict(attribution),
        "structure": {
            "by_class": by_class,
            "by_sector": by_sector,
            "as_of": as_of,
        },
        "total_value": total_mv,
        "today_pct": attribution.total_pct,
    }
