"""Tool: get_financials — key income-statement + financial-indicator metrics."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

from app.tools.base import Tool, ToolError

if TYPE_CHECKING:
    from app.services.tushare_service import TushareService


class FinancialsArgs(BaseModel):
    ts_code: str
    period: Literal["latest", "quarterly", "annual"] = "latest"
    end_date: str | None = None  # 指定期间末(YYYYMMDD,如 20241231=2024年报);给则精确选该期


def _select_period_row(df, *, end_date: str | None, period: str):
    """从多期历史财报 df 选目标期那一行。

    真 tushare 一次返回全历史(~100+ 期),早先 ``.iloc[0]`` 永远取最新期 → 问"2024年报"
    却给"2026一季报"(mock 时代每查只吐一期的遗留)。这里按问的期间精确选:
      - end_date 给 → 选 end_date == 该值的行(精确期间);
      - period=annual → 最新一个年报(end_date 以 1231 结尾);
      - period=quarterly → 最新一个非年报季报;
      - latest → 最新一期。
    """
    if df.empty or "end_date" not in df.columns:
        return None
    s = df.sort_values("end_date", ascending=False)
    ed = s["end_date"].astype(str)
    if end_date:
        hit = s[ed == str(end_date)]
        return hit.iloc[0] if len(hit) else None
    if period == "annual":
        hit = s[ed.str.endswith("1231")]
        return hit.iloc[0] if len(hit) else None
    if period == "quarterly":
        hit = s[~ed.str.endswith("1231")]
        return hit.iloc[0] if len(hit) else None
    return s.iloc[0]


def _num_or_none(v: Any) -> float | None:
    """可空数值字段:None / NaN / ±inf → None(否则进 JSON 缓存写 PG 会 'Infinity' 报错毒事务)。"""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _finite(v: Any, default: float = 0.0) -> float:
    """非空数值字段:None / NaN / ±inf → default(同样防非有限值污染 JSON 缓存)。"""
    f = _num_or_none(v)
    return default if f is None else f


class GetFinancialsTool(Tool):
    """Return key financial metrics for a given A-share.

    Data source: TushareService.get_income (profit / loss statement)
    and TushareService.get_fina_indicator (financial ratios).
    按 end_date / period 选目标期(见 _select_period_row);字段 revenue / n_income
    与评测 gold 生成口径(generator._INCOME_COLS)对齐。
    """

    name = "get_financials"
    description = (
        "Return key income-statement + financial-indicator metrics for a given "
        "A-share (ts_code): revenue, net_profit, roe, gross_margin (销售毛利率 %), "
        "debt_to_assets (资产负债率 %), YoY growth (revenue_yoy / net_profit_yoy, "
        "annual %), eps (每股收益, 元/股) and bps (每股净资产, 元/股). "
        "period: 'latest' | 'quarterly' | 'annual'; end_date (YYYYMMDD) selects a "
        "specific report period (e.g. 20241231 = FY2024 annual). "
        "Note: pe is always 0.0; use get_daily_basic for P/E data."
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

        # 选问的那一期(非永远最新);字段对齐 gold:revenue / n_income。
        revenue: float = 0.0
        net_profit: float = 0.0
        row = _select_period_row(income_df, end_date=validated.end_date, period=validated.period)
        if row is not None:
            revenue = _finite(row.get("revenue", row.get("total_revenue", 0.0)))
            net_profit = _finite(row.get("n_income", row.get("n_income_attr_p", 0.0)))

        # C55: read the correct fina_indicator columns.
        # Previously: 'roe' was read from netprofit_margin (mislabeled) and 'pe' from eps (wrong).
        # Fix: roe → fi_row['roe'] (tushare fina_indicator includes roe in both real and mock paths).
        #      pe_ttm is NOT in fina_indicator; set pe=0.0 until sourced from daily_basic separately.
        roe: float = 0.0
        pe: float = 0.0
        revenue_yoy: float | None = None  # 营收同比(or_yoy,年度,%);供"同比增速"题直取
        net_profit_yoy: float | None = None  # 净利润同比(netprofit_yoy,年度,%)
        eps: float | None = None  # 每股收益(元/股);估值题反推 PE 理论价用
        bps: float | None = None  # 每股净资产(元/股);估值题反推 PB 理论价用
        gross_margin: float | None = None  # 销售毛利率(grossprofit_margin,%)
        debt_to_assets: float | None = None  # 资产负债率(debt_to_assets,%)
        fi_row = _select_period_row(fina_df, end_date=validated.end_date, period=validated.period)

        if fi_row is not None:
            roe = _finite(fi_row.get("roe", 0.0))
            # pe_ttm is not in fina_indicator — callers should source it from get_daily_basic.
            pe = 0.0
            revenue_yoy = _num_or_none(fi_row.get("or_yoy"))
            net_profit_yoy = _num_or_none(fi_row.get("netprofit_yoy"))
            # eps/bps/毛利率/资产负债率 与 gold(generator _FINA_COLS / build_valuation_cases)
            # 同源同期:fina_indicator 该期行。补齐后模型一次取全 5 个财报指标。
            eps = _num_or_none(fi_row.get("eps"))
            bps = _num_or_none(fi_row.get("bps"))
            gross_margin = _num_or_none(fi_row.get("grossprofit_margin"))
            debt_to_assets = _num_or_none(fi_row.get("debt_to_assets"))

        return {
            "ts_code": validated.ts_code,
            "period": validated.period,
            "revenue_yoy": revenue_yoy,
            "net_profit_yoy": net_profit_yoy,
            "revenue": revenue,
            "net_profit": net_profit,
            "roe": roe,
            "pe": pe,
            "eps": eps,
            "bps": bps,
            "gross_margin": gross_margin,
            "debt_to_assets": debt_to_assets,
        }
