"""build_trend_cases 离线单测:stub 喂已知 q_sales_yoy/netprofit_yoy,验直取 + 选期 + 跳空。"""

import asyncio

import pandas as pd
from eval.question_gen import generator, intents, stock_pool


class _StubTushare:
    """fina_indicator 多期(含 20241231)带 yoy 字段;income 走财报取数同一 fetch。"""

    async def get_fina_indicator(self, *, ts_code, end_date=None):
        return pd.DataFrame(
            [
                {
                    "end_date": "20250930",
                    "roe": 99.9,
                    "debt_to_assets": 99.9,
                    "grossprofit_margin": 99.9,
                    "or_yoy": 99.9,
                    "q_sales_yoy": 99.9,
                    "netprofit_yoy": 99.9,
                },
                {
                    "end_date": "20241231",
                    "roe": 34.46,
                    "debt_to_assets": 16.4,
                    "grossprofit_margin": 91.2,
                    "or_yoy": 12.34,
                    "q_sales_yoy": 88.88,
                    "netprofit_yoy": 8.76,
                },
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
        generator.build_trend_cases(
            _StubTushare(), "20260612", "20241231", "2024年年报", lambda tag: f"qg-{tag}"
        )
    )


def test_build_trend_cases_count_shape_period():
    cases = _run()
    assert len(cases) == len(stock_pool.POOL) * 2  # 营收同比 + 净利同比
    for c in cases:
        assert c.intent == intents.INTENT_TREND_SIGNAL
        assert c.gold_shape == "scalar"
        assert c.difficulty == "中等"
        assert c.window == "2024年年报"
        assert c.meta["period_end"] == "20241231"
        assert c.tolerance == {"kind": "rel", "value": 0.01}  # ±1%


def test_build_trend_cases_gold_equals_budget_field_and_selects_period():
    cases = _run()
    rev_yoy = next(c for c in cases if c.indicator == "营收同比")
    assert (
        rev_yoy.gold == 12.34
    )  # 营收同比取年度 or_yoy@20241231,非单季 q_sales_yoy(88.88)/20250930(99.9)
    np_yoy = next(c for c in cases if c.indicator == "净利同比")
    assert np_yoy.gold == 8.76  # netprofit_yoy
    assert "营收同比增速" in rev_yoy.question
    assert "净利润同比增速" in np_yoy.question
