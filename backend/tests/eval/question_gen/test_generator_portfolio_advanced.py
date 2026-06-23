"""build_portfolio_advanced_cases 离线单测:难档 portfolio_calc 两道(TWR + 三层归因)。

stub 给确定性 3 日 close + 当日 pct_chg → 断言 gold 等于 oracle
(compute_twr / compute_daily_attribution)的输出、requires_run_python、difficulty、gold_shape。
"""

import asyncio

import pandas as pd
from app.services.portfolio_analytics import (
    DailySnap,
    HoldingDaily,
    compute_daily_attribution,
    compute_twr,
)
from eval.question_gen import generator, intents, stock_pool

# 2 只白酒(同板块,≥2 成员 → 出一篮)
_TWO_STOCKS = (
    stock_pool.Stock("600519.SH", "贵州茅台", "白酒"),
    stock_pool.Stock("000858.SZ", "五粮液", "白酒"),
)

# 已知 3 连续交易日(到 as_of=20260612);每只股各日 close + 当日 pct_chg。
_DATES = ["20260610", "20260611", "20260612"]
# 茅台:100 → 110 → 121(每日 +10%);五粮液:200 → 210 → 220.5(+5%)
_CLOSE = {
    "600519.SH": [100.0, 110.0, 121.0],
    "000858.SZ": [200.0, 210.0, 220.5],
}
_PCT = {
    "600519.SH": [10.0, 10.0, 10.0],
    "000858.SZ": [5.0, 5.0, 5.0],
}


class _StubTushare:
    """get_daily(start,end) -> 该股 3 日 close + pct_chg + trade_date(升序)。"""

    async def get_daily(self, *, ts_code, start, end):
        return pd.DataFrame(
            {
                "trade_date": _DATES,
                "close": _CLOSE[ts_code],
                "pct_chg": _PCT[ts_code],
            }
        )


def _run():
    return asyncio.run(
        generator.build_portfolio_advanced_cases(
            _StubTushare(),
            "20260612",
            lambda tag: f"qg-{tag}",
            pool=_TWO_STOCKS,
        )
    )


def _expected_twr() -> float:
    # qty 第 j 只 = 100*(j+1):茅台 100,五粮液 200。
    snaps = [
        DailySnap(
            date=_DATES[i],
            holdings={
                "600519.SH": (100, _CLOSE["600519.SH"][i]),
                "000858.SZ": (200, _CLOSE["000858.SZ"][i]),
            },
        )
        for i in range(3)
    ]
    return compute_twr(snaps)["cumulative"] * 100


def _expected_attribution() -> dict:
    # today_pct = 当日(末日)pct_chg;基准 = 篮子内等权均值。
    today = {"600519.SH": 10.0, "000858.SZ": 5.0}
    market_pct = (10.0 + 5.0) / 2  # 篮子全体等权
    # 同板块(白酒)这两只等权 = 同上(都白酒)
    sector_pct = market_pct
    qty = {"600519.SH": 100, "000858.SZ": 200}
    last_close = {"600519.SH": 121.0, "000858.SZ": 220.5}
    holdings = [
        HoldingDaily(
            ts_code=c,
            asset_class="stock",
            market_value=qty[c] * last_close[c],
            today_pct=today[c],
            sector="白酒",
            sector_pct=sector_pct,
            market_pct=market_pct,
        )
        for c in ("600519.SH", "000858.SZ")
    ]
    return compute_daily_attribution(holdings).stock_breakdown


def test_advanced_cases_count_and_flags():
    cases = _run()
    assert len(cases) == 2  # 1 篮 × (TWR + 归因)
    for c in cases:
        assert c.intent == intents.INTENT_PORTFOLIO
        assert c.difficulty == "复杂"
        assert c.requires_run_python is True


def test_twr_case_gold_and_shape():
    cases = _run()
    twr = next(c for c in cases if c.indicator == "账户TWR")
    assert twr.gold_shape == "scalar"
    assert twr.gold == round(_expected_twr(), 6)
    assert "TWR" in twr.question


def test_attribution_case_gold_and_shape():
    cases = _run()
    attr = next(c for c in cases if c.indicator == "收益归因")
    assert attr.gold_shape == "multi_scalar"
    expected = _expected_attribution()
    # gold 三个数值(标签不参与判分)逐一等于 oracle 输出。
    assert sorted(attr.gold.values()) == sorted(expected.values())
    assert "大盘" in attr.question and "行业" in attr.question
