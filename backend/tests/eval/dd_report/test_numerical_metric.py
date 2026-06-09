"""M2 NumericalMetric — extraction regex + tushare ±1% 容差.

L0 unit: fake tushare adapter, 验数字归一 + 容差判定 + 4 类指标支持。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from eval.dd_report.metrics.base import CaseMeta, MetricInputs
from eval.dd_report.metrics.numerical_metric import (
    NumericalMetric,
    parse_chinese_number,
)


class _FakeTushareAdapter:
    """fake adapter, 不限 cut_off, 直接返回固定数据."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetch_income(self, ts_code: str, **kwargs: Any) -> list[dict[str, Any]]:
        return self._rows


def _make_inputs(report: dict[str, Any], adapter: Any) -> MetricInputs:
    return MetricInputs(
        report=report,
        case_meta=CaseMeta(
            case_id="bt-test",
            ts_code="600519.SH",
            target_name="茅台",
            cut_off_date=date(2024, 6, 30),
        ),
        tushare_adapter=adapter,
        kb_lookup=None,
        evaluator_clients={},
    )


def test_parse_yi_yuan() -> None:
    assert parse_chinese_number("150 亿元") == pytest.approx(1.5e10)
    assert parse_chinese_number("150亿") == pytest.approx(1.5e10)
    assert parse_chinese_number("3.5亿元") == pytest.approx(3.5e8)


def test_parse_wan_yuan() -> None:
    assert parse_chinese_number("8000 万元") == pytest.approx(8e7)


def test_parse_percent() -> None:
    assert parse_chinese_number("12.5%") == pytest.approx(0.125)
    assert parse_chinese_number("12.5 %") == pytest.approx(0.125)


def test_parse_bad_returns_none() -> None:
    assert parse_chinese_number("无") is None
    assert parse_chinese_number("约") is None


def test_revenue_within_tolerance_counts_correct() -> None:
    report = {
        "financial_analysis": {
            "key_metrics": [
                {"name": "营业收入", "value": "150 亿元", "period": "2024 H1"},
            ],
        },
    }
    # tushare income 返回真值 150.0 亿元 (revenue 列, 单位 元)
    adapter = _FakeTushareAdapter(
        [{"end_date": "20240630", "revenue": 1.501e10}],  # 0.07% 偏离, < 1% pass
    )
    m = NumericalMetric()
    r = m.compute(_make_inputs(report, adapter))
    assert r.details["total"] == 1
    assert r.details["correct"] == 1
    assert r.value == 1.0


def test_revenue_outside_tolerance_counts_wrong() -> None:
    report = {
        "financial_analysis": {
            "key_metrics": [
                {"name": "营业收入", "value": "200 亿元", "period": "2024 H1"},
            ],
        },
    }
    adapter = _FakeTushareAdapter(
        [{"end_date": "20240630", "revenue": 1.5e10}],  # 33% 偏离
    )
    m = NumericalMetric()
    r = m.compute(_make_inputs(report, adapter))
    assert r.details["total"] == 1
    assert r.details["correct"] == 0
    assert r.details["wrong_values"][0]["metric_name"] == "营业收入"


def test_unknown_metric_skipped() -> None:
    report = {
        "financial_analysis": {
            "key_metrics": [
                {"name": "某未知指标", "value": "100 万元", "period": "2024 H1"},
            ],
        },
    }
    adapter = _FakeTushareAdapter([])
    m = NumericalMetric()
    r = m.compute(_make_inputs(report, adapter))
    assert r.details["total"] == 0
    assert r.value == 1.0  # vacuous
