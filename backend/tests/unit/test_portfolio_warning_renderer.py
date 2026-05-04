"""Unit tests for portfolio_warning_renderer."""

from __future__ import annotations

from datetime import datetime

from app.agents.portfolio_warning_renderer import render_portfolio_warning_markdown
from app.agents.portfolio_warning_schema import (
    DeepDiveSection,
    PortfolioWarningReport,
    RiskDiagnosis,
)
from app.services.monitoring.signal_rules.base import SignalLevel, SignalResult


def _build_report(level: SignalLevel, with_deep_dive: bool = False) -> PortfolioWarningReport:
    return PortfolioWarningReport(
        customer_id="c1",
        customer_name="测试公司",
        ts_code="600519.SH",
        industry="消费",
        run_id="r1",
        alert_id="a1",
        generated_at=datetime(2026, 5, 4, 16, 30),
        alert_level=level,
        summary="测试综述",
        triggered_signals=[
            SignalResult(
                rule_name="cash_flow",
                level=SignalLevel.YELLOW,
                detected_value=35.0,
                threshold=30.0,
                explanation="现金流恶化",
            ),
        ]
        if level != SignalLevel.GREEN
        else [],
        risk_diagnosis=RiskDiagnosis(narrative="风险...", severity="medium")
        if level != SignalLevel.GREEN
        else None,
        deep_dive=DeepDiveSection(content="深度调查...") if with_deep_dive else None,
        recommendations=["关注现金流"] if level != SignalLevel.GREEN else [],
        data_sources=["tushare"],
        data_limitations=[],
        references=[],
    )


def test_green_renders_minimum() -> None:
    md = render_portfolio_warning_markdown(_build_report(SignalLevel.GREEN))
    assert "测试公司" in md
    assert "GREEN" in md.upper() or "正常" in md or "绿色" in md


def test_yellow_renders_signals() -> None:
    md = render_portfolio_warning_markdown(_build_report(SignalLevel.YELLOW))
    assert "cash_flow" in md
    assert "现金流恶化" in md


def test_red_with_deep_dive_renders_section() -> None:
    md = render_portfolio_warning_markdown(_build_report(SignalLevel.RED, with_deep_dive=True))
    assert "深度调查" in md


def test_yellow_no_deep_dive_no_section() -> None:
    md = render_portfolio_warning_markdown(_build_report(SignalLevel.YELLOW))
    assert "深度调查" not in md
