"""build_valuation_cases 离线单测:stub 同 pe/pb/eps/bps,验聚合 + 公式 + 题面。"""

import asyncio

import pandas as pd
from eval.question_gen import generator, intents, stock_pool


class _StubVal:
    async def get_daily_basic(self, *, ts_code, trade_date=None):
        return pd.DataFrame([{"pe": 20.0, "pb": 5.0}])

    async def get_fina_indicator(self, *, ts_code, end_date=None):
        return pd.DataFrame([{"end_date": "20241231", "eps": 4.0, "bps": 10.0}])


def _run():
    return asyncio.run(
        generator.build_valuation_cases(
            _StubVal(), "20260612", "20241231", "2024年年报", lambda t: f"qg-{t}"
        )
    )


def test_build_valuation_cases_values():
    cases = _run()
    # 所有股 pe=20/pb=5/eps=4/bps=10;5 个板块都≥2 成员 → 15 股 ×(PE理论价+PB理论价)=30
    assert len(cases) == len(stock_pool.POOL) * 2
    for c in cases:
        assert c.intent == intents.INTENT_VALUATION
        assert c.gold_shape == "scalar"
    pe = next(c for c in cases if c.indicator == "PE理论价")
    assert pe.gold == 80.0  # 4 × (20+20)/2
    pb = next(c for c in cases if c.indicator == "PB理论价")
    assert pb.gold == 50.0  # 10 × (5+5)/2
