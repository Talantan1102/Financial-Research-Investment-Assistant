"""build_financial_cases 离线单测:stub 返回多期 DataFrame,验过滤选期 + 单位 + 跳空。"""

import asyncio

import pandas as pd

from eval.question_gen import generator, intents, stock_pool


class _StubTushare:
    """fina_indicator / income 都返回多期历史(含 20241231),验生成器按 end_date 选行。"""

    async def get_fina_indicator(self, *, ts_code, end_date=None):
        return pd.DataFrame([
            {"end_date": "20250930", "roe": 99.9, "debt_to_assets": 99.9, "grossprofit_margin": 99.9},
            {"end_date": "20241231", "roe": 34.46, "debt_to_assets": 16.4, "grossprofit_margin": 91.2},
        ])

    async def get_income(self, *, ts_code, end_date=None):
        return pd.DataFrame([
            {"end_date": "20250930", "revenue": 1.0, "n_income": 1.0},
            {"end_date": "20241231", "revenue": 170_900_000_000.0, "n_income": 86_000_000_000.0},
        ])


def _run():
    return asyncio.run(
        generator.build_financial_cases(_StubTushare(), "20241231", "2024年年报", lambda tag: f"qg-{tag}")
    )


def test_build_financial_cases_count_shape_period():
    cases = _run()
    assert len(cases) == len(stock_pool.POOL) * 5  # 5 指标
    for c in cases:
        assert c.intent == intents.INTENT_FINANCIAL
        assert c.gold_shape == "scalar"
        assert c.window == "2024年年报"
        assert c.meta["period_end"] == "20241231"


def test_build_financial_cases_selects_right_period_and_unit():
    cases = _run()
    roe = next(c for c in cases if c.indicator == "ROE")
    assert roe.gold == 34.46  # 选 20241231 行,不是 20250930 的 99.9
    rev = next(c for c in cases if c.indicator == "营收")
    assert rev.gold == 1709.0  # 元→亿
    assert "亿元" in rev.question
