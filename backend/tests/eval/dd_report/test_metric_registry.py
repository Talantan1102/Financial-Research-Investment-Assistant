"""MetricRegistry — Phase 2 T2.0."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from eval.dd_report.metrics.base import (
    CaseMeta,
    MetricInputs,
    MetricRegistry,
    MetricResult,
)


class _AlwaysOneMetric:
    name = "always_one"

    def compute(self, inputs: MetricInputs) -> MetricResult:
        return MetricResult(name=self.name, value=1.0, details={})


class _AlwaysZeroMetric:
    name = "always_zero"

    def compute(self, inputs: MetricInputs) -> MetricResult:
        return MetricResult(name=self.name, value=0.0, details={"reason": "test"})


def _make_inputs() -> MetricInputs:
    return MetricInputs(
        report={"target_name": "茅台"},
        case_meta=CaseMeta(
            case_id="bt-x",
            ts_code="600519.SH",
            target_name="茅台",
            cut_off_date=date(2024, 6, 30),
        ),
        ground_truth=None,
        tushare_adapter=None,
        kb_lookup=None,
        evaluator_clients={},
    )


def test_registry_runs_all_metrics_in_order() -> None:
    reg = MetricRegistry([_AlwaysOneMetric(), _AlwaysZeroMetric()])
    results = reg.compute_all(_make_inputs())
    assert [r.name for r in results] == ["always_one", "always_zero"]
    assert results[0].value == 1.0
    assert results[1].details == {"reason": "test"}


def test_registry_duplicate_name_raises() -> None:
    with pytest.raises(ValueError, match="duplicate metric name"):
        MetricRegistry([_AlwaysOneMetric(), _AlwaysOneMetric()])


def test_registry_empty_returns_empty_list() -> None:
    reg = MetricRegistry([])
    assert reg.compute_all(_make_inputs()) == []


def _ignore_unused(_: Any) -> None:
    pass
