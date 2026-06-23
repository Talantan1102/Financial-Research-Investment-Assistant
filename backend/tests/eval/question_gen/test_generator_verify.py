"""build_verify_cases 离线单测:stub 返回多期 DataFrame,验真值 gold + 声称值扰动 + 容差。"""

import asyncio

import pandas as pd
from eval.question_gen import generator, intents, stock_pool


class _StubTushare:
    """income 返回多期历史(含 20241231),验生成器取真实营收/净利做 gold(不是声称值)。"""

    async def get_fina_indicator(self, *, ts_code, end_date=None):
        return pd.DataFrame(
            [
                {"end_date": "20250930", "roe": 99.9},
                {"end_date": "20241231", "roe": 34.46},
            ]
        )

    async def get_income(self, *, ts_code, end_date=None):
        return pd.DataFrame(
            [
                {"end_date": "20250930", "revenue": 1.0, "n_income": 1.0},
                {
                    "end_date": "20241231",
                    "revenue": 170_900_000_000.0,
                    "n_income": 86_000_000_000.0,
                },
            ]
        )


def _run():
    return asyncio.run(
        generator.build_verify_cases(
            _StubTushare(), "20260612", "20241231", "2024年年报", lambda tag: f"qg-{tag}"
        )
    )


def test_build_verify_cases_count_shape_period():
    cases = _run()
    assert len(cases) == len(stock_pool.POOL) * 2  # 营收 + 净利
    for c in cases:
        assert c.intent == intents.INTENT_FINANCIAL_VERIFY
        assert c.gold_shape == "scalar"
        assert c.window == "2024年年报"
        assert c.meta["period_end"] == "20241231"
        assert c.tolerance == {"kind": "rel", "value": 0.01}


def test_build_verify_cases_gold_is_real_value_not_claimed():
    cases = _run()
    rev = next(c for c in cases if c.indicator == "营收")
    assert rev.gold == 1709.0  # 真实营收(元→亿),选 20241231 行
    ni = next(c for c in cases if c.indicator == "净利")
    assert ni.gold == 860.0  # 真实净利(元→亿)


def test_build_verify_cases_claimed_is_perturbed():
    cases = _run()
    rev = next(c for c in cases if c.indicator == "营收")
    assert rev.meta["claimed"] == round(1709.0 * 1.05, 2)  # 真值 ×1.05
    assert str(rev.meta["claimed"]) in rev.question  # 声称值嵌进题面
    assert rev.gold != rev.meta["claimed"]  # gold 是真值,不是声称值
