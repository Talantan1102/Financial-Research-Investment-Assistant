"""build_portfolio_cases 离线单测:stub 同 close,权重由合成 qty 决定。"""

import asyncio

import pandas as pd
from eval.question_gen import generator, intents


class _StubClose:
    async def get_daily_basic(self, *, ts_code, trade_date=None):
        return pd.DataFrame([{"close": 100.0}])


def _run():
    return asyncio.run(
        generator.build_portfolio_cases(_StubClose(), "20260612", lambda t: f"qg-{t}")
    )


def test_build_portfolio_cases_count_and_values():
    cases = _run()
    # 板块成员>=2 的板块:白酒5/银行3/新能源3/医药2/电子2 = 5 板块 ×(权重+HHI)=10
    assert len(cases) == 10
    for c in cases:
        assert c.intent == intents.INTENT_PORTFOLIO
        assert c.gold_shape == "scalar"
    # 白酒 5 只 qty 100..500 close 100 → 权重 [1..5]/15;w0=1/15→6.6667%;HHI=55/225=0.2444
    w = next(c for c in cases if c.indicator == "持仓权重" and c.meta["板块"] == "白酒")
    assert abs(w.gold - 6.6667) < 0.01
    hhi = next(c for c in cases if c.indicator == "HHI" and c.meta["板块"] == "白酒")
    assert abs(hhi.gold - 0.2444) < 0.001
