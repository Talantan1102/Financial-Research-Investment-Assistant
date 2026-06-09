"""L1 — Analyst _maybe_run_debate hook + Writer post_process 拷 debate fields (v1.x A5b).

Phase 2 Task 5 wire 测试(去推荐改造后 § 6 = InvestmentSynthesis 综合研判):
1. Analyst.step() 调 _maybe_run_debate, state_update 含 debate_trace
2. Analyst.step() _maybe_run_debate 返 None → state_update 不含 debate_trace key
3. Writer.post_process_writer_output rounds_completed=2 → 拷 v2 进 InvestmentSynthesis
4. Writer.post_process_writer_output rounds_completed=1 → fallback 拷 v1
5. state.debate_trace=None → bull_case/bear_case 仍 default empty

spec ref: docs/superpowers/specs/2026-05-16-v1.x-bull-bear-debate-design.md § 8
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from app.agents.debate_schemas import AdvocateOutput, DebateTrace
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


def _mk_advocate_output(label: str) -> AdvocateOutput:
    return AdvocateOutput(
        arguments=[f"{label}_1", f"{label}_2", f"{label}_3"],
        strongest_argument=f"{label}_strongest",
        rebut_targets=[],
        confidence="high",
    )


def test_analyst_step_runs_debate_when_orchestrator_succeeds() -> None:
    """Analyst.step() 调 _maybe_run_debate, state_update 含 debate_trace."""
    from app.agents.analyst import Analyst
    from app.agents.schemas import ResearchState

    llm = MagicMock()
    llm.chat = MagicMock(
        return_value=MagicMock(content='{"insights": []}', model="m", cost_cny=0.001)
    )
    analyst = Analyst(llm=llm)

    state = ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
        target_ts_code="600519.SH",
    )

    fake_trace = DebateTrace(
        bull_v1=_mk_advocate_output("bull_v1"),
        bear_v1=_mk_advocate_output("bear_v1"),
        bull_v2=_mk_advocate_output("bull_v2"),
        bear_v2=_mk_advocate_output("bear_v2"),
        total_cost_cny=0.003,
        total_latency_ms=500,
        rounds_completed=2,
    )
    analyst._maybe_run_debate = MagicMock(return_value=fake_trace)  # type: ignore[method-assign]

    result = analyst.step(state)
    assert "debate_trace" in result.state_update
    assert result.state_update["debate_trace"] is fake_trace


def test_analyst_step_skips_debate_when_orchestrator_returns_none() -> None:
    """Analyst.step() 调 _maybe_run_debate 返 None → state_update 不含 debate_trace."""
    from app.agents.analyst import Analyst
    from app.agents.schemas import ResearchState

    llm = MagicMock()
    llm.chat = MagicMock(
        return_value=MagicMock(content='{"insights": []}', model="m", cost_cny=0.001)
    )
    analyst = Analyst(llm=llm)
    state = ResearchState(user_id="u", session_id="s", user_message="m", request_id="r")
    analyst._maybe_run_debate = MagicMock(return_value=None)  # type: ignore[method-assign]

    result = analyst.step(state)
    assert "debate_trace" not in result.state_update


def test_writer_post_process_copies_debate_fields_when_v2_present() -> None:
    """rounds_completed=2 → InvestmentSynthesis 拷 v2 4 字段."""
    from app.agents.schemas import ResearchState
    from app.agents.writer import post_process_writer_output

    bull_v2 = _mk_advocate_output("bull_v2")
    bear_v2 = _mk_advocate_output("bear_v2")
    trace = DebateTrace(
        bull_v1=_mk_advocate_output("bull_v1"),
        bear_v1=_mk_advocate_output("bear_v1"),
        bull_v2=bull_v2,
        bear_v2=bear_v2,
        total_cost_cny=0.003,
        total_latency_ms=500,
        rounds_completed=2,
    )
    state = ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
        target_ts_code="600519.SH",
        risk_tolerance="moderate",
        debate_trace=trace,
    )

    minimal_report = _build_minimal_report_fixture()

    out = post_process_writer_output(state, minimal_report)
    assert out.investment_synthesis.bull_case == list(bull_v2.arguments)
    assert out.investment_synthesis.bear_case == list(bear_v2.arguments)
    assert out.investment_synthesis.strongest_bull_point == bull_v2.strongest_argument
    assert out.investment_synthesis.strongest_bear_point == bear_v2.strongest_argument


def test_writer_post_process_uses_v1_when_rounds_completed_1() -> None:
    """rounds_completed=1 (v2 fallback) → 拷 v1 作 final."""
    from app.agents.schemas import ResearchState
    from app.agents.writer import post_process_writer_output

    bull_v1 = _mk_advocate_output("bull_v1")
    bear_v1 = _mk_advocate_output("bear_v1")
    trace = DebateTrace(
        bull_v1=bull_v1,
        bear_v1=bear_v1,
        bull_v2=None,
        bear_v2=None,
        total_cost_cny=0.001,
        total_latency_ms=200,
        rounds_completed=1,
    )
    state = ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
        target_ts_code="600519.SH",
        risk_tolerance="moderate",
        debate_trace=trace,
    )
    minimal_report = _build_minimal_report_fixture()
    out = post_process_writer_output(state, minimal_report)

    assert out.investment_synthesis.bull_case == list(bull_v1.arguments)
    assert out.investment_synthesis.bear_case == list(bear_v1.arguments)
    assert out.investment_synthesis.strongest_bull_point == bull_v1.strongest_argument
    assert out.investment_synthesis.strongest_bear_point == bear_v1.strongest_argument


def test_writer_post_process_no_debate_keeps_empty_fields() -> None:
    """state.debate_trace = None → bull_case/bear_case 仍 default empty."""
    from app.agents.schemas import ResearchState
    from app.agents.writer import post_process_writer_output

    state = ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
        target_ts_code="600519.SH",
        risk_tolerance="moderate",
        debate_trace=None,
    )
    minimal_report = _build_minimal_report_fixture()
    out = post_process_writer_output(state, minimal_report)
    assert out.investment_synthesis.bull_case == []
    assert out.investment_synthesis.bear_case == []
    assert out.investment_synthesis.strongest_bull_point is None
    assert out.investment_synthesis.strongest_bear_point is None


def _build_minimal_report_fixture() -> InvestmentDueDiligenceReport:
    """Minimal valid InvestmentDueDiligenceReport — cp from test_analyst_valuation_integration.py."""
    return InvestmentDueDiligenceReport(
        target_name="贵州茅台",
        target_ts_code="600519.SH",
        request_id="r",
        generated_at=datetime(2026, 5, 16, 10, 0, 0),
        target_overview=TargetOverview(
            narrative="标的综述",
            main_business="白酒生产销售",
            current_market_cap=1_000_000_000_000.0,
        ),
        legal_qualification=LegalQualification(
            narrative="资质综述",
            legal_status="合规",
            business_qualifications=[],
            adverse_records=[],
        ),
        financial_analysis=FinancialAnalysis(
            narrative="财务综述",
            key_metrics=[],
            profitability_analysis="盈利分析",
            growth_analysis="成长分析",
            return_analysis="回报分析",
            cash_flow_analysis="现金流分析",
            valuation_analysis=ValuationAnalysis(narrative="LLM 占位"),
        ),
        industry_analysis=IndustryAnalysis(
            narrative="行业综述",
            industry_name="白酒",
            industry_outlook="景气",
            competitive_position="龙头",
            key_competitors=[],
            policy_impact="无重大影响",
        ),
        risk_assessment=RiskAssessment(
            narrative="风险综述",
            market_risk=[],
            growth_risk=[],
            event_risk=[],
            valuation_risk=[],
            overall_risk_level="medium",
        ),
        investment_synthesis=InvestmentSynthesis(
            narrative="LLM 综合研判综述",
            key_judgment_factors=["需求景气度"],
            valuation_context="当前价位于内在价值区间下沿。",
        ),
    )
