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


def _make_inputs(report: dict, gt: _FakeGroundTruth) -> MetricInputs:
    return MetricInputs(
        report=report,
        case_meta=CaseMeta("bt-test", "600519.SH", "茅台", date(2024, 6, 30)),
        ground_truth=gt,  # type: ignore[arg-type]
        tushare_adapter=None,
        kb_lookup=None,
        evaluator_clients={},
    )


def _report_buy_target_1700_1900_risk(risk_titles: list[str]) -> dict:
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


def test_no_ground_truth_returns_all_none() -> None:
    gt = _FakeGroundTruth(kline=[], anns=[])
    m = PredictionMetric()
    r = m.compute(_make_inputs(_report_buy_target_1700_1900_risk([]), gt))
    assert r.details["direction_correct"] is None
    assert r.details["target_price_hit"] is None
    assert r.details["risk_flag_realized_rate"] is None
