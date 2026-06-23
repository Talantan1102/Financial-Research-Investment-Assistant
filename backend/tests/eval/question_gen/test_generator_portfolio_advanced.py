"""build_portfolio_advanced_cases 离线单测:难档 portfolio_calc(TWR per-板块 + 跨板块三层归因)。

stub 给确定性 3 日 close + 当日 pct_chg → 断言 gold 等于 oracle
(compute_twr / compute_daily_attribution)的输出、requires_run_python、difficulty、gold_shape。

归因篮子跨 ≥2 板块、每板块 ≥2 成员 → 三层都非平凡(行业超额 sector_excess ≠ 0)。
TWR 仍按板块出(每个 ≥2 成员的板块一道)。
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

# 跨 2 板块、每板块 2 只 → 归因篮子跨板块(三层非平凡),TWR 仍每板块一道。
_CROSS_STOCKS = (
    # 白酒(同日涨幅 +10% / +5%)
    stock_pool.Stock("600519.SH", "贵州茅台", "白酒"),
    stock_pool.Stock("000858.SZ", "五粮液", "白酒"),
    # 银行(同日涨幅 +1% / +2% → 板块均值明显≠全篮均值)
    stock_pool.Stock("600036.SH", "招商银行", "银行"),
    stock_pool.Stock("601398.SH", "工商银行", "银行"),
)

# 已知 3 连续交易日(到 as_of=20260612);每只股各日 close + 当日 pct_chg。
_DATES = ["20260610", "20260611", "20260612"]
_CLOSE = {
    "600519.SH": [100.0, 110.0, 121.0],  # +10%/日
    "000858.SZ": [200.0, 210.0, 220.5],  # +5%/日
    "600036.SH": [30.0, 30.3, 30.603],  # +1%/日
    "601398.SH": [5.0, 5.1, 5.202],  # +2%/日
}
_PCT = {
    "600519.SH": [10.0, 10.0, 10.0],
    "000858.SZ": [5.0, 5.0, 5.0],
    "600036.SH": [1.0, 1.0, 1.0],
    "601398.SH": [2.0, 2.0, 2.0],
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


def _run(pool=_CROSS_STOCKS):
    return asyncio.run(
        generator.build_portfolio_advanced_cases(
            _StubTushare(),
            "20260612",
            lambda tag: f"qg-{tag}",
            pool=pool,
        )
    )


def _expected_twr(codes: tuple[str, ...]) -> float:
    # qty 第 j 只 = 100*(j+1)(按该板块内顺序)。
    qty = {c: 100 * (j + 1) for j, c in enumerate(codes)}
    snaps = [
        DailySnap(
            date=_DATES[i],
            holdings={c: (qty[c], _CLOSE[c][i]) for c in codes},
        )
        for i in range(3)
    ]
    return compute_twr(snaps)["cumulative"] * 100


def _expected_attribution() -> dict:
    # 跨板块篮子:前 2 板块(白酒、银行)各取前 2 只 → 4 只 4 仓。
    # qty = 100*(j+1) 按篮子全局顺序;today_pct = 当日(末日)pct_chg。
    codes = ("600519.SH", "000858.SZ", "600036.SH", "601398.SH")
    sector_of = {
        "600519.SH": "白酒",
        "000858.SZ": "白酒",
        "600036.SH": "银行",
        "601398.SH": "银行",
    }
    today = {c: _PCT[c][-1] for c in codes}
    qty = {c: 100 * (j + 1) for j, c in enumerate(codes)}
    last_close = {c: _CLOSE[c][-1] for c in codes}
    # market_pct = 全篮等权;sector_pct = 各自板块内成员等权。
    market_pct = sum(today.values()) / len(today)
    sector_pct = {}
    for c in codes:
        sec = sector_of[c]
        same = [today[x] for x in codes if sector_of[x] == sec]
        sector_pct[c] = sum(same) / len(same)
    holdings = [
        HoldingDaily(
            ts_code=c,
            asset_class="stock",
            market_value=qty[c] * last_close[c],
            today_pct=today[c],
            sector=sector_of[c],
            sector_pct=sector_pct[c],
            market_pct=market_pct,
        )
        for c in codes
    ]
    return compute_daily_attribution(holdings).stock_breakdown


def test_advanced_cases_count_and_flags():
    cases = _run()
    # 2 板块各 1 道 TWR + 1 道跨板块归因 = 3 道。
    twrs = [c for c in cases if c.indicator == "账户TWR"]
    attrs = [c for c in cases if c.indicator == "收益归因"]
    assert len(twrs) == 2
    assert len(attrs) == 1
    for c in cases:
        assert c.intent == intents.INTENT_PORTFOLIO
        assert c.difficulty == "复杂"
        assert c.requires_run_python is True


def test_twr_case_gold_and_shape():
    cases = _run()
    twrs = {c.meta["板块"]: c for c in cases if c.indicator == "账户TWR"}
    assert set(twrs) == {"白酒", "银行"}
    twr_baijiu = twrs["白酒"]
    assert twr_baijiu.gold_shape == "scalar"
    assert twr_baijiu.gold == round(_expected_twr(("600519.SH", "000858.SZ")), 6)
    assert "TWR" in twr_baijiu.question
    twr_bank = twrs["银行"]
    assert twr_bank.gold == round(_expected_twr(("600036.SH", "601398.SH")), 6)


def test_attribution_cross_sector_gold_and_shape():
    cases = _run()
    attr = next(c for c in cases if c.indicator == "收益归因")
    assert attr.gold_shape == "multi_scalar"
    assert attr.difficulty == "复杂"
    assert attr.requires_run_python is True
    expected = _expected_attribution()
    # 三层都非平凡:行业超额(sector_excess)不再恒为 0。
    assert expected["sector_excess"] != 0.0
    assert attr.gold["sector_excess"] != 0.0
    # gold 三值逐一等于 oracle 输出(标签与口径一致)。
    assert attr.gold == expected
    # 篮子跨板块:题面含两个板块的成员。
    assert "招商银行" in attr.question and "贵州茅台" in attr.question
    assert "大盘" in attr.question and "行业" in attr.question


def test_attribution_skipped_when_single_sector():
    # 只有 1 个 ≥2 成员的板块 → 凑不出跨板块篮子 → 不出归因题(只出 TWR),不报错。
    single = (
        stock_pool.Stock("600519.SH", "贵州茅台", "白酒"),
        stock_pool.Stock("000858.SZ", "五粮液", "白酒"),
    )
    cases = _run(pool=single)
    assert [c for c in cases if c.indicator == "收益归因"] == []
    assert len([c for c in cases if c.indicator == "账户TWR"]) == 1
