"""Unit tests for SignalRule ABC + types."""

from __future__ import annotations

import pytest
from app.services.monitoring.signal_rules.base import (
    SignalLevel,
    SignalResult,
    SignalRule,
)
from app.services.monitoring.signal_rules.defaults import DEFAULT_THRESHOLDS


def test_signal_level_enum() -> None:
    assert SignalLevel.GREEN.value == "green"
    assert SignalLevel.YELLOW.value == "yellow"
    assert SignalLevel.RED.value == "red"


def test_signal_result_serializable() -> None:
    r = SignalResult(
        rule_name="financial_ratio",
        level=SignalLevel.YELLOW,
        detected_value=0.85,
        threshold=0.80,
        explanation="资产负债率超阈值",
        raw_data_ref={"ts_code": "x"},
    )
    dumped = r.model_dump()
    assert dumped["rule_name"] == "financial_ratio"
    assert dumped["level"] == "yellow"


def test_signal_rule_is_abstract() -> None:
    with pytest.raises(TypeError):
        SignalRule()  # type: ignore[abstract]


def test_default_thresholds_has_5_rules() -> None:
    assert set(DEFAULT_THRESHOLDS.keys()) == {
        "financial_ratio",
        "cash_flow",
        "shareholder_count",
        "announcement",
        "price_anomaly",
    }
