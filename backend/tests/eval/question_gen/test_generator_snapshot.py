"""build_snapshot_cases 离线单测:用固定 stub tushare(非 oracle,只验生成逻辑)。"""

import asyncio

import pandas as pd

from eval.question_gen import generator, intents


class _StubTushare:
    """固定返回一行 daily_basic 的 stub -- 确定性,仅供测生成逻辑,非真值 oracle。"""

    async def get_daily_basic(self, *, ts_code, trade_date=None):
        return pd.DataFrame(
            [{"pe": 25.0, "pb": 8.0, "turnover_rate": 1.5, "dv_ratio": 2.0}]
        )


def _run():
    return asyncio.run(
        generator.build_snapshot_cases(_StubTushare(), "20260612", lambda tag: f"qg-{tag}")
    )


def test_build_snapshot_cases_count_and_shape():
    cases = _run()
    # 股票池只数 × 4 指标(POOL 当前 15 只 → 60)
    assert len(cases) == len(__import__("eval.question_gen.stock_pool", fromlist=["POOL"]).POOL) * 4
    for c in cases:
        assert c.intent == intents.INTENT_SNAPSHOT
        assert c.difficulty == "简单"
        assert c.gold_shape == "scalar"
        assert c.window == "snapshot"
        assert c.meta["trade_date"] == "20260612"


def test_build_snapshot_cases_pe_gold_and_question():
    cases = _run()
    pe = next(c for c in cases if c.indicator == "PE")
    assert pe.gold == 25.0
    assert "市盈率" in pe.question
    assert len(pe.stocks) == 1


class _StubTushareNullPE:
    """PE 为 None 的亏损股 stub。"""

    async def get_daily_basic(self, *, ts_code, trade_date=None):
        return pd.DataFrame([{"pe": None, "pb": 8.0, "turnover_rate": 1.5, "dv_ratio": 2.0}])


def test_build_snapshot_cases_skips_null_field():
    from eval.question_gen import stock_pool

    cases = asyncio.run(
        generator.build_snapshot_cases(_StubTushareNullPE(), "20260612", lambda tag: f"qg-{tag}")
    )
    # 每股 PE 为 None 被跳过 → 每股 3 个指标
    assert len(cases) == len(stock_pool.POOL) * 3
    assert all(c.indicator != "PE" for c in cases)
