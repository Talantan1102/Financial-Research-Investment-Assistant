"""M4 PredictionMetric — reasoning backtest accuracy.

3 子指标:
  1. recommendation_direction_correct: 建议方向 vs 后续股价方向
  2. target_price_hit: 后续 horizon 内是否触及 target_price_range
  3. risk_flag_realized_rate: 报告 RiskItem 关键词在后续公告 title 命中率
"""

from __future__ import annotations

from datetime import date
from typing import Any

from eval.dd_report.metrics.base import CaseMeta, MetricInputs
from eval.dd_report.metrics.prediction_metric import PredictionMetric


class _FakeGroundTruth:
    def __init__(
        self,
        kline: list[dict[str, Any]],
        anns: list[dict[str, Any]],
    ) -> None:
        self._kline = kline
        self._anns = anns

    def fetch_post_cut_off_kline(
        self, ts_code: str, cut_off: date, horizon_days: int = 90
    ) -> list[dict[str, Any]]:
        return self._kline

    def fetch_post_cut_off_anns(
        self, ts_code: str, cut_off: date, horizon_days: int = 90
    ) -> list[dict[str, Any]]:
        return self._anns


def _make_inputs(report: dict[str, Any], gt: _FakeGroundTruth) -> MetricInputs:
    return MetricInputs(
        report=report,
        case_meta=CaseMeta("bt-test", "600519.SH", "茅台", date(2024, 6, 30)),
        ground_truth=gt,  # type: ignore[arg-type]
        tushare_adapter=None,
        kb_lookup=None,
        evaluator_clients={},
    )


def _report_buy_target_1700_1900_risk(risk_titles: list[str]) -> dict[str, Any]:
    return {
        "target_close_price_at_gen": 1500.0,
        "investment_recommendation": {
            "recommendation": "recommend_buy",
            "estimated_target_price_range": {"low": 1700.0, "high": 1900.0},
        },
        "risk_assessment": {
            "market_risk": [
                {"title": t, "description": "", "severity": "medium", "mitigations": []}
                for t in risk_titles
            ],
            "growth_risk": [],
            "event_risk": [],
            "valuation_risk": [],
        },
    }


def test_direction_buy_and_price_rises_is_correct() -> None:
    gt = _FakeGroundTruth(
        kline=[
            {"trade_date": "20240701", "close": 1550.0},
            {"trade_date": "20240901", "close": 1750.0},  # rose 16%
        ],
        anns=[],
    )
    m = PredictionMetric()
    r = m.compute(_make_inputs(_report_buy_target_1700_1900_risk([]), gt))
    assert r.details["direction_correct"] is True


def test_direction_buy_but_price_drops_incorrect() -> None:
    gt = _FakeGroundTruth(
        kline=[
            {"trade_date": "20240701", "close": 1450.0},
            {"trade_date": "20240901", "close": 1350.0},
        ],
        anns=[],
    )
    m = PredictionMetric()
    r = m.compute(_make_inputs(_report_buy_target_1700_1900_risk([]), gt))
    assert r.details["direction_correct"] is False


def test_target_price_hit_when_high_touched() -> None:
    gt = _FakeGroundTruth(
        kline=[
            {"trade_date": "20240701", "close": 1550.0},
            {"trade_date": "20240801", "high": 1750.0, "close": 1700.0},  # 触及 1700-1900
            {"trade_date": "20240901", "close": 1620.0},
        ],
        anns=[],
    )
    m = PredictionMetric()
    r = m.compute(_make_inputs(_report_buy_target_1700_1900_risk([]), gt))
    assert r.details["target_price_hit"] is True


def test_target_price_hit_false_when_high_above_range() -> None:
    """T2.5 bug-fix guard: bar with high above target range ceiling must NOT count
    as hit. The plan-prescribed `or float(h) >= low` clause was dropped because
    a bar breaking past `high` shouldn't credit hit — this test守护 the fix."""
    gt = _FakeGroundTruth(
        kline=[
            {"trade_date": "20240701", "close": 1550.0},
            {"trade_date": "20240801", "high": 2100.0, "close": 2000.0},  # above 1900 ceiling
        ],
        anns=[],
    )
    m = PredictionMetric()
    r = m.compute(_make_inputs(_report_buy_target_1700_1900_risk([]), gt))
    assert r.details["target_price_hit"] is False


def test_risk_flag_realized_match_in_announcement_title() -> None:
    gt = _FakeGroundTruth(
        kline=[{"trade_date": "20240701", "close": 1500.0}],
        anns=[
            {"ann_date": "20240801", "title": "公司就被ST退市风险提示"},
            {"ann_date": "20240901", "title": "正常中报披露"},
        ],
    )
    report = _report_buy_target_1700_1900_risk(["退市风险", "供应链中断"])
    m = PredictionMetric()
    r = m.compute(_make_inputs(report, gt))
    # 退市 命中, 供应链中断 不命中 -> 1/2 = 0.5
    assert r.details["risk_flag_realized_rate"] == 0.5


def test_value_mean_of_three_subs_when_all_non_none() -> None:
    """All 3 sub-indicators populate: direction=True (1.0), target_price=True (1.0),
    risk_flag=1.0 (one keyword matched). value = (1+1+1)/3 = 1.0."""
    gt = _FakeGroundTruth(
        kline=[
            {"trade_date": "20240701", "high": 1620.0, "close": 1600.0},
            {"trade_date": "20240801", "high": 1750.0, "close": 1720.0},  # hits 1700-1900
            {
                "trade_date": "20240901",
                "high": 1800.0,
                "close": 1750.0,
            },  # last close 1750 vs anchor 1500 = +16.7%
        ],
        anns=[
            {"ann_date": "20240801", "title": "公司就被ST退市风险提示"},
        ],
    )
    report = _report_buy_target_1700_1900_risk(["退市风险"])
    m = PredictionMetric()
    r = m.compute(_make_inputs(report, gt))
    assert r.details["direction_correct"] is True
    assert r.details["target_price_hit"] is True
    assert r.details["risk_flag_realized_rate"] == 1.0
    assert r.value == 1.0


def test_no_ground_truth_returns_all_none() -> None:
    gt = _FakeGroundTruth(kline=[], anns=[])
    m = PredictionMetric()
    r = m.compute(_make_inputs(_report_buy_target_1700_1900_risk([]), gt))
    assert r.details["direction_correct"] is None
    assert r.details["target_price_hit"] is None
    assert r.details["risk_flag_realized_rate"] is None
