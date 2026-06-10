"""Unit tests for Writer in alert_writer mode (v0.8.3 B-3)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from app.agents.portfolio_warning_schema import (
    PortfolioWarningReport,
    RiskDiagnosis,
)
from app.agents.schemas import ResearchState
from app.agents.writer import Writer, _build_alert_prompt
from app.services.monitoring.signal_rules.base import SignalLevel, SignalResult


def _make_warning_report() -> PortfolioWarningReport:
    return PortfolioWarningReport(
        customer_id="c1",
        customer_name="x",
        ts_code="600519.SH",
        industry="白酒",
        run_id="r",
        alert_id="a",
        generated_at=datetime(2026, 5, 4),
        alert_level=SignalLevel.YELLOW,
        summary="发现现金流异常风险,建议关注",
        triggered_signals=[],
        risk_diagnosis=RiskDiagnosis(narrative="经营现金流持续下滑", severity="medium"),
        recommendations=["加强监控", "补充材料"],
        data_sources=["tushare"],
    )


def _llm_returning(report: PortfolioWarningReport) -> MagicMock:
    """Build a sync mock LLM that returns a parsed PortfolioWarningReport."""
    fake = MagicMock()
    response = MagicMock()
    response.parsed = report
    response.cost_cny = 0.5
    response.model = "mock-model"
    # chat is sync (mirrors real LLMService.chat)
    fake.chat = MagicMock(return_value=response)
    return fake


def _alert_state(signals: list[SignalResult] | None = None) -> ResearchState:
    return ResearchState(
        user_id="u",
        session_id="s",
        user_message="alert",
        request_id="r",
        mode="alert_deep_dive",
        alert_signals=signals
        or [
            SignalResult(
                rule_name="cash_flow",
                level=SignalLevel.YELLOW,
                explanation="经营现金流同比下降 35%",
            )
        ],
    )


# ---------------------------------------------------------------------------
# alert_deep_dive mode tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_writer_alert_mode_produces_portfolio_warning_report() -> None:
    """run() in alert_deep_dive mode must return state with portfolio_warning_report set."""
    expected = _make_warning_report()
    writer = Writer(llm=_llm_returning(expected))
    state = _alert_state()

    new_state = await writer.run(state)

    assert new_state.portfolio_warning_report is not None
    assert new_state.portfolio_warning_report.alert_level == SignalLevel.YELLOW
    assert new_state.portfolio_warning_report.customer_id == "c1"


@pytest.mark.asyncio
async def test_writer_alert_mode_does_not_set_investment_report() -> None:
    """Alert mode must NOT touch investment_report — different deliverable."""
    expected = _make_warning_report()
    writer = Writer(llm=_llm_returning(expected))
    state = _alert_state()

    new_state = await writer.run(state)

    # investment_report stays None in alert mode
    assert new_state.investment_report is None


@pytest.mark.asyncio
async def test_writer_alert_mode_calls_llm_with_fast_tier() -> None:
    """Alert writer uses 'fast' tier (short task, cheap)."""
    expected = _make_warning_report()
    fake_llm = _llm_returning(expected)
    writer = Writer(llm=fake_llm)
    state = _alert_state()

    await writer.run(state)

    call_kwargs = fake_llm.chat.call_args
    assert call_kwargs is not None
    # tier must be "fast"
    tier_arg = call_kwargs.kwargs.get("tier") or call_kwargs.args[1]
    assert tier_arg == "fast"


@pytest.mark.asyncio
async def test_writer_alert_mode_raises_when_parsed_is_none() -> None:
    """If LLM returns no parsed object, alert writer raises RuntimeError."""
    fake = MagicMock()
    response = MagicMock()
    response.parsed = None
    fake.chat = MagicMock(return_value=response)
    writer = Writer(llm=fake)
    state = _alert_state()

    with pytest.raises(RuntimeError, match="alert writer LLM returned no parsed"):
        await writer.run(state)


# ---------------------------------------------------------------------------
# full_research mode — backward-compat guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_writer_full_research_mode_via_run() -> None:
    """run() in full_research mode must delegate to step() and return ResearchState."""
    from app.agents.investment_dd_schema import (
        FinancialAnalysis,
        IndustryAnalysis,
        InvestmentDueDiligenceReport,
        InvestmentSynthesis,
        LegalQualification,
        RiskAssessment,
        TargetOverview,
        ValuationAnalysis,
    )

    fake_report = InvestmentDueDiligenceReport(
        target_name="贵州茅台",
        target_ts_code="600519.SH",
        request_id="req-test",
        generated_at=datetime(2026, 5, 4),
        target_overview=TargetOverview(
            narrative="综述",
            main_business="白酒",
            evidence=["chunk-001"],
        ),
        legal_qualification=LegalQualification(
            narrative="合规",
            legal_status="正常",
            business_qualifications=[],
            adverse_records=[],
            evidence=["chunk-001"],
        ),
        financial_analysis=FinancialAnalysis(
            narrative="财务分析",
            key_metrics=[],
            profitability_analysis="盈利能力强",
            growth_analysis="成长性良好",
            return_analysis="ROE 高",
            cash_flow_analysis="现金流充裕",
            valuation_analysis=ValuationAnalysis(narrative="估值合理"),
            evidence=["chunk-001"],
        ),
        industry_analysis=IndustryAnalysis(
            narrative="行业分析",
            industry_name="白酒",
            industry_outlook="景气",
            competitive_position="龙头",
            key_competitors=[],
            policy_impact="政策利好",
            evidence=["chunk-001"],
        ),
        risk_assessment=RiskAssessment(
            narrative="风险评估",
            market_risk=[],
            growth_risk=[],
            event_risk=[],
            valuation_risk=[],
            overall_risk_level="low",
            evidence=["chunk-001"],
        ),
        investment_synthesis=InvestmentSynthesis(
            narrative="综合研判:基本面稳健,估值合理。",
            key_judgment_factors=["需求景气度"],
            valuation_context="当前价位于内在价值区间下沿。",
            bull_case=["龙头护城河深"],
            bear_case=["估值对需求敏感"],
            evidence=["chunk-001"],
        ),
    )

    fake = MagicMock()
    response = MagicMock()
    response.parsed = fake_report
    response.model = "mock-model"
    response.cost_cny = 1.0
    fake.chat = MagicMock(return_value=response)

    writer = Writer(llm=fake)
    state = ResearchState(
        user_id="u",
        session_id="s",
        user_message="投资尽调",
        request_id="req-test",
        mode="full_research",
    )

    new_state = await writer.run(state)

    assert new_state.investment_report is not None
    assert new_state.investment_report.target_name == "贵州茅台"
    assert new_state.report_markdown is not None
    # alert fields stay None
    assert new_state.portfolio_warning_report is None


# ---------------------------------------------------------------------------
# _build_alert_prompt unit test (pure function)
# ---------------------------------------------------------------------------


def test_build_alert_prompt_includes_signals() -> None:
    state = _alert_state(
        signals=[
            SignalResult(
                rule_name="cash_flow",
                level=SignalLevel.YELLOW,
                explanation="经营现金流下滑",
            ),
            SignalResult(
                rule_name="price_anomaly",
                level=SignalLevel.RED,
                explanation="股价单日跌幅 -9.8%",
            ),
        ]
    )
    prompt = _build_alert_prompt(state)
    assert "cash_flow" in prompt
    assert "yellow" in prompt
    assert "price_anomaly" in prompt
    assert "red" in prompt
    assert "PortfolioWarningReport" in prompt


def test_build_alert_prompt_empty_signals() -> None:
    state = ResearchState(
        user_id="u",
        session_id="s",
        user_message="alert",
        request_id="r",
        mode="alert_deep_dive",
        alert_signals=None,
    )
    prompt = _build_alert_prompt(state)
    assert "PortfolioWarningReport" in prompt
    # No signals — empty list, prompt still valid
    assert "触发信号" in prompt
