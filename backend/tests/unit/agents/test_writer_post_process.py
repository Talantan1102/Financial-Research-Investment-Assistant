"""Unit tests — Writer post_process_writer_output(去推荐改造后)。

去推荐改造(2026-06-04):post_process 不再用 Python 覆盖评级 / 仓位(推荐引擎已下线)。
现在只做两件事:
- A5a:若 state.valuation_analysis 非空,以 state 覆盖 LLM 占位估值(见
  test_analyst_valuation_integration.py)。
- A5b:若跑了 bull/bear debate,把 final 论据注入 § 6 InvestmentSynthesis。

spec ref: docs/superpowers/specs/2026-05-16-v1.x-bull-bear-debate-design.md § 8
"""

from __future__ import annotations

from datetime import datetime

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
from app.agents.schemas import ResearchState
from app.agents.writer import build_investment_dd_prompt, post_process_writer_output


def _make_state(**kwargs: object) -> ResearchState:
    defaults: dict[str, object] = {
        "user_id": "test",
        "session_id": "sess-1",
        "user_message": "请对贵州茅台进行投资尽调。",
        "request_id": "req-1",
        "target_ts_code": "600519.SH",
        "client_total_aum": 10_000_000.0,
        "investment_objective": "balanced",
        "investment_horizon": "medium_term",
        "risk_tolerance": "moderate",
    }
    defaults.update(kwargs)
    return ResearchState(**defaults)  # type: ignore[arg-type]


def _make_dd_report() -> InvestmentDueDiligenceReport:
    """Build a minimal InvestmentDueDiligenceReport(去推荐后 § 6 = 综合研判)。"""
    return InvestmentDueDiligenceReport(
        target_name="贵州茅台",
        target_ts_code="600519.SH",
        request_id="req-1",
        generated_at=datetime(2026, 5, 5, 10, 0, 0),
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
            valuation_analysis=ValuationAnalysis(narrative="估值综述"),
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
            narrative="LLM 给出的综合研判(多空待 debate 注入)",
            key_judgment_factors=["需求景气度"],
            valuation_context="当前价位于内在价值区间下沿。",
        ),
    )


def _mk_advocate_output(label: str) -> AdvocateOutput:
    return AdvocateOutput(
        arguments=[f"{label}_1", f"{label}_2", f"{label}_3"],
        strongest_argument=f"{label}_strongest",
        rebut_targets=[],
        confidence="high",
    )


def test_writer_post_process_no_debate_no_valuation_returns_unchanged() -> None:
    """既无 debate 也无 valuation_analysis → post_process 幂等不改任何字段。"""
    state = _make_state()
    llm_report = _make_dd_report()
    out = post_process_writer_output(state, llm_report)
    assert out == llm_report
    # § 6 综合研判保持 LLM 原样
    assert out.investment_synthesis.narrative == llm_report.investment_synthesis.narrative
    assert out.investment_synthesis.bull_case == []
    assert out.investment_synthesis.bear_case == []


def test_writer_post_process_deterministic() -> None:
    """同 (state, llm_report) 多次调用必须产生一致输出 (idempotent)。"""
    bull = _mk_advocate_output("bull_v2")
    bear = _mk_advocate_output("bear_v2")
    trace = DebateTrace(
        bull_v1=_mk_advocate_output("bull_v1"),
        bear_v1=_mk_advocate_output("bear_v1"),
        bull_v2=bull,
        bear_v2=bear,
        total_cost_cny=0.003,
        total_latency_ms=500,
        rounds_completed=2,
    )
    state = _make_state(debate_trace=trace)
    llm_report = _make_dd_report()
    out1 = post_process_writer_output(state, llm_report)
    out2 = post_process_writer_output(state, llm_report)
    assert out1 == out2


def test_writer_post_process_injects_debate_into_synthesis() -> None:
    """A5b:debate final 论据注入 § 6 综合研判 bull_case / bear_case / strongest_*。"""
    bull = _mk_advocate_output("bull_v2")
    bear = _mk_advocate_output("bear_v2")
    trace = DebateTrace(
        bull_v1=_mk_advocate_output("bull_v1"),
        bear_v1=_mk_advocate_output("bear_v1"),
        bull_v2=bull,
        bear_v2=bear,
        total_cost_cny=0.003,
        total_latency_ms=500,
        rounds_completed=2,
    )
    state = _make_state(debate_trace=trace)
    llm_report = _make_dd_report()
    out = post_process_writer_output(state, llm_report)

    syn = out.investment_synthesis
    assert syn.bull_case == list(bull.arguments)
    assert syn.bear_case == list(bear.arguments)
    assert syn.strongest_bull_point == bull.strongest_argument
    assert syn.strongest_bear_point == bear.strongest_argument
    # narrative / 其它综合研判字段保持 LLM 原样
    assert syn.narrative == llm_report.investment_synthesis.narrative
    assert syn.key_judgment_factors == llm_report.investment_synthesis.key_judgment_factors
    assert syn.valuation_context == llm_report.investment_synthesis.valuation_context


def test_writer_post_process_preserves_other_sections_when_injecting_debate() -> None:
    """注入 debate 时,§ 6 以外的 section 必须保持原样。"""
    bull = _mk_advocate_output("bull_v2")
    bear = _mk_advocate_output("bear_v2")
    trace = DebateTrace(
        bull_v1=_mk_advocate_output("bull_v1"),
        bear_v1=_mk_advocate_output("bear_v1"),
        bull_v2=bull,
        bear_v2=bear,
        total_cost_cny=0.003,
        total_latency_ms=500,
        rounds_completed=2,
    )
    state = _make_state(debate_trace=trace)
    llm_report = _make_dd_report()
    out = post_process_writer_output(state, llm_report)

    assert out.target_overview == llm_report.target_overview
    assert out.financial_analysis == llm_report.financial_analysis
    assert out.industry_analysis == llm_report.industry_analysis
    assert out.risk_assessment == llm_report.risk_assessment


def test_writer_prompt_contains_sop_section() -> None:
    """v0.8.5 — Writer prompt 必须含 SOP 11 维度方法论 section。"""
    state = _make_state()
    prompt = build_investment_dd_prompt(state)
    assert "投资研究员 SOP" in prompt or "11 维度方法论" in prompt
    # 至少 11 关键词中的代表性几个出现
    for kw in [
        "偿债",
        "盈利",
        "成长",
        "现金流",
        "估值",
        "行业",
        "股东",
        "资金流",
        "事件",
        "风险",
        "决策",
    ]:
        assert kw in prompt, f"writer prompt missing SOP keyword: {kw}"
