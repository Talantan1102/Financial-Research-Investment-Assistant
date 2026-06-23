"""build_percentile_cases 离线单测:stub 给已知 PE 历史序列 + 当日 PE,验生成逻辑与 gold。

难档(复杂)意图 valuation_percentile:gold = oracle.pe_percentile(history, current)*100,
requires_run_python=True(答案应由 agent 写代码算整段序列的分位)。
"""

import asyncio

import pandas as pd
from eval import indicator_oracle
from eval.question_gen import generator, intents, stock_pool


class _StubTushare:
    """确定性 stub:区间查 daily_basic 返回 4 点 PE 历史[10,20,30,40];单日查返回当日 PE=25。

    get_daily_basic(trade_date=...) -> 单行(当日 pe);
    get_daily_basic(start_date=..., end_date=...) -> 多行(历史 pe 序列,trade_date 升序)。
    """

    async def get_daily_basic(self, *, ts_code, trade_date=None, start_date=None, end_date=None):
        if start_date is not None or end_date is not None:
            return pd.DataFrame(
                {
                    "ts_code": [ts_code] * 4,
                    "trade_date": ["20230101", "20230401", "20230701", "20231001"],
                    "pe": [10.0, 20.0, 30.0, 40.0],
                }
            )
        return pd.DataFrame(
            [{"pe": 25.0, "pb": 8.0, "turnover_rate": 1.5, "dv_ratio": 2.0}]
        )


def _run(pool=None):
    return asyncio.run(
        generator.build_percentile_cases(
            _StubTushare(),
            "20260612",
            lambda tag: f"qg-{tag}",
            pool=pool if pool is not None else stock_pool.POOL,
        )
    )


def test_build_percentile_cases_gold_and_shape():
    cases = _run()
    assert len(cases) == len(stock_pool.POOL)  # 每只一道
    expected = indicator_oracle.pe_percentile([10.0, 20.0, 30.0, 40.0], 25.0) * 100
    assert expected == 50.0  # sanity:2/4 历史 < 25
    for c in cases:
        assert c.intent == intents.INTENT_VALUATION_PERCENTILE
        assert c.difficulty == "复杂"
        assert c.gold_shape == "scalar"
        assert c.gold == expected
        assert c.requires_run_python is True
        assert len(c.stocks) == 1
        assert "分位" in c.question


class _StubTushareEmptyHistory:
    """历史序列为空 -> 该股应被跳过。"""

    async def get_daily_basic(self, *, ts_code, trade_date=None, start_date=None, end_date=None):
        if start_date is not None or end_date is not None:
            return pd.DataFrame({"ts_code": [], "trade_date": [], "pe": []})
        return pd.DataFrame(
            [{"pe": 25.0, "pb": 8.0, "turnover_rate": 1.5, "dv_ratio": 2.0}]
        )


def test_build_percentile_cases_skips_empty_history():
    cases = asyncio.run(
        generator.build_percentile_cases(
            _StubTushareEmptyHistory(), "20260612", lambda tag: f"qg-{tag}"
        )
    )
    assert cases == []


class _StubTushareNullCurrent:
    """当日 PE 缺失 -> 该股应被跳过。"""

    async def get_daily_basic(self, *, ts_code, trade_date=None, start_date=None, end_date=None):
        if start_date is not None or end_date is not None:
            return pd.DataFrame({"ts_code": [ts_code] * 2, "pe": [10.0, 20.0]})
        return pd.DataFrame(
            [{"pe": None, "pb": 8.0, "turnover_rate": 1.5, "dv_ratio": 2.0}]
        )


def test_build_percentile_cases_skips_null_current():
    cases = asyncio.run(
        generator.build_percentile_cases(
            _StubTushareNullCurrent(), "20260612", lambda tag: f"qg-{tag}"
        )
    )
    assert cases == []
