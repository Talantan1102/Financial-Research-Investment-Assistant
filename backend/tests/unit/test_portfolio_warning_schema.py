"""Unit tests for PortfolioWarningReport schema."""

from __future__ import annotations

from datetime import datetime

import pytest
from app.agents.portfolio_warning_schema import (
    DeepDiveSection,
    PortfolioWarningReport,
    ReferenceItem,
    RiskDiagnosis,
)
from app.services.monitoring.signal_rules.base import SignalLevel, SignalResult
from pydantic import ValidationError


def _green_report() -> PortfolioWarningReport:
    return PortfolioWarningReport(
        customer_id="c1",
        customer_name="x",
        ts_code="x.SH",
        industry="x",
        run_id="r1",
        alert_id="a1",
        generated_at=datetime(2026, 5, 4, 16, 30),
        alert_level=SignalLevel.GREEN,
        summary="一切正常",
        triggered_signals=[],
        risk_diagnosis=None,
        deep_dive=None,
        recommendations=[],
        data_sources=["tushare"],
        data_limitations=[],
        references=[],
    )


def test_green_report_validates() -> None:
    report = _green_report()
    assert report.alert_level == SignalLevel.GREEN


def test_yellow_report_with_signals() -> None:
    report = _green_report().model_copy(
        update={
            "alert_level": SignalLevel.YELLOW,
            "summary": "有 1 项风险",
            "triggered_signals": [
                SignalResult(rule_name="cash_flow", level=SignalLevel.YELLOW, explanation="x"),
            ],
            "risk_diagnosis": RiskDiagnosis(narrative="风险叙述", severity="medium"),
            "recommendations": ["关注现金流"],
        }
    )
    assert report.alert_level == SignalLevel.YELLOW
    assert len(report.triggered_signals) == 1


def test_red_with_deep_dive() -> None:
    report = _green_report().model_copy(
        update={
            "alert_level": SignalLevel.RED,
            "summary": "高危",
            "deep_dive": DeepDiveSection(
                content="深度调查内容...", evidence_chunk_ids=["c1", "c2"]
            ),
            "recommendations": ["紧急回访"],
        }
    )
    assert report.deep_dive is not None
    assert len(report.deep_dive.evidence_chunk_ids) == 2


def test_extra_field_rejected() -> None:
    with pytest.raises(ValidationError):
        PortfolioWarningReport.model_validate({"customer_id": "x", "_extra": "bad"})


def test_reference_item_basic() -> None:
    ref = ReferenceItem(source="tushare:income", url=None, snippet="...")
    assert ref.source == "tushare:income"
