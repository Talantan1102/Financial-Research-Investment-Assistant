from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class HoldingDaily:
    ts_code: str
    asset_class: str            # stock / fund_etf / fund_otc / bond / gold / cash
    market_value: float         # 当前市值(权重分母)
    today_pct: float            # 该持仓当日涨跌 %
    sector: str | None = None
    sector_pct: float | None = None     # 所属板块当日 %(仅 stock 用)
    market_pct: float | None = None     # 大盘(沪深300)当日 %(仅 stock 用)


@dataclass
class AttributionResult:
    total_pct: float
    by_class: dict[str, float]
    stock_breakdown: dict[str, float]   # market / sector_excess / idiosyncratic
    contributions: list[dict] = field(default_factory=list)  # 每只票对总盘的贡献,供"哪几只拖累最大"


def compute_daily_attribution(holdings: list[HoldingDaily]) -> AttributionResult:
    """确定性拆账。无现金流口径:只拆'市场赚赔'。MVP 取 beta≈1。"""
    total_mv = sum(h.market_value for h in holdings)
    if total_mv <= 0:
        return AttributionResult(0.0, {}, {"market": 0.0, "sector_excess": 0.0, "idiosyncratic": 0.0})

    by_class: dict[str, float] = {}
    contributions: list[dict] = []
    market = sector_excess = idio = 0.0

    for h in holdings:
        w = h.market_value / total_mv
        contrib = w * h.today_pct                 # 该持仓对总盘的贡献(百分点)
        by_class[h.asset_class] = by_class.get(h.asset_class, 0.0) + contrib
        contributions.append({"ts_code": h.ts_code, "asset_class": h.asset_class, "contrib_pct": contrib})

        if h.asset_class == "stock" and h.market_pct is not None and h.sector_pct is not None:
            market += w * h.market_pct
            sector_excess += w * (h.sector_pct - h.market_pct)
            idio += w * (h.today_pct - h.sector_pct)

    total = sum(by_class.values())
    contributions.sort(key=lambda c: c["contrib_pct"])  # 最拖累的在前
    return AttributionResult(
        total_pct=round(total, 6),
        by_class={k: round(v, 6) for k, v in by_class.items()},
        stock_breakdown={"market": round(market, 6), "sector_excess": round(sector_excess, 6), "idiosyncratic": round(idio, 6)},
        contributions=contributions,
    )
