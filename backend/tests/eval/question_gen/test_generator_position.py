"""build_position_cases 离线单测:stub 返回带 close 的 daily_basic。"""

import asyncio

import pandas as pd

from eval.question_gen import generator, intents, stock_pool


class _StubClose:
    async def get_daily_basic(self, *, ts_code, trade_date=None):
        return pd.DataFrame([{"close": 100.0, "pe": 1.0, "pb": 1.0, "turnover_rate": 1.0, "dv_ratio": 1.0}])


def _run():
    return asyncio.run(generator.build_position_cases(_StubClose(), "20260612", lambda t: f"qg-{t}"))


def test_build_position_cases_count_and_values():
    cases = _run()
    assert len(cases) == len(stock_pool.POOL) * 2
    for c in cases:
        assert c.intent == intents.INTENT_POSITION
        assert c.gold_shape == "scalar"
    mv = next(c for c in cases if c.indicator == "单仓市值")  # 第一只 qty=100, close=100 → 10000
    assert mv.gold == 10000.0
    pnl = next(c for c in cases if c.indicator == "单仓浮盈")  # cost=round(100*0.85,2)=85 → 100*(100-85)=1500
    assert pnl.gold == 1500.0
