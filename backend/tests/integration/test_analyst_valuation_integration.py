"""L1 — Analyst valuation_analysis hook + Writer post_process 拷贝整合 (v1.x A5a).

Phase 3 Task 15 wire 测试:
1. Analyst._maybe_compute_valuation_analysis tool_results 空 → None (graceful skip)
2. Writer.post_process_writer_output 在 state.valuation_analysis is not None 时
   覆盖 report.financial_analysis.valuation_analysis (Python 决定论)
3. state.valuation_analysis is None → LLM 占位保留

spec ref: docs/superpowers/specs/2026-05-16-v1.x-multi-valuation-cross-check-design.md § 8
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

from app.agents.analyst import Analyst
from app.agents.investment_dd_schema import (
    FinancialAnalysis,
    IndustryAnalysis,
    InvestmentDueDiligenceReport,
    InvestmentRecommendation,
    LegalQualification,
    PriceRange,
    RiskAssessment,
    TargetOverview,
    ValuationAnalysis,
    ValuationModel,
)
from app.agents.schemas import ResearchState, ToolResult
from app.agents.writer import post_process_writer_output


def _tr(name: str, output: dict[str, Any]) -> ToolResult:
    return ToolResult(
        tool_name=name,
        args={"ts_code": "600519.SH"},
        success=True,
        output=output,
        latency_ms=10,
    )


def _make_state_with_complete_tool_results() -> ResearchState:
    """ResearchState with 4 核心 tool_results + pe_history + cashflow — Analyst 真产 VA."""
    tool_results = [
        _tr("get_stock_quote", {"price": 1800.0, "change_pct": 1.0, "volume": 1000.0}),
        _tr(
            "get_daily_basic",
            {
                "ts_code": "600519.SH",
                "pe": 25.0,
                "pb": 8.0,
                "ps": 8.0,
                "dv_ratio": 1.2,
                "total_mv": 22000000.0,
                "circ_mv": 22000000.0,
                "turnover_rate": 0.5,
            },
        ),
        _tr(
            "get_financials",
            {
                "ts_code": "600519.SH",
                "period": "latest",
                "revenue": 1000000000.0,
                "net_profit": 500000000.0,
                "roe": 30.0,
                "pe": 25.0,
            },
        ),
        _tr(
            "get_balance_sheet",
            {
                "ts_code": "600519.SH",
                "total_assets": 100000000.0,
                "total_liab": 20000000.0,
                "total_cur_assets": 50000000.0,
                "total_cur_liab": 15000000.0,
                "asset_liability_ratio": 0.2,
                "current_ratio": 3.3,
            },
        ),
        _tr(
            "get_cashflow",
            {
                "ts_code": "600519.SH",
                "n_cashflow_act": 300000000.0,
                "n_cashflow_inv_act": -50000000.0,
                "n_cash_flows_fnc_act": -10000000.0,
                "positive_ocf": True,
            },
        ),
        _tr(
            "get_pe_history",
            {
                "ts_code": "600519.SH",
                "current_pe": 25.0,
                "historical_percentile": 0.4,
                "min_pe": 15.0,
                "max_pe": 50.0,
                "median_pe": 28.0,
                "valuation_band": "合理",
            },
        ),
    ]
    return ResearchState(
        user_id="test",
        session_id="s",
        user_message="尽调 600519.SH 贵州茅台 白酒",
        request_id="r",
        target_ts_code="600519.SH",
        target_entity="贵州茅台",
        client_total_aum=10_000_000.0,
        investment_objective="balanced",
        investment_horizon="medium_term",
        risk_tolerance="moderate",
        tool_results=tool_results,
    )


def _make_minimal_state() -> ResearchState:
    """Minimal ResearchState — tool_results 空 → _maybe_compute_valuation_analysis 返 None."""
    return ResearchState(
        user_id="test",
        session_id="s",
        user_message="尽调茅台",
        request_id="r",
        target_ts_code="600519.SH",
        risk_tolerance="moderate",
    )


def _make_state_with_precomputed_va() -> ResearchState:
    """state.valuation_analysis 已被 Analyst 填好;用于测 Writer post_process 拷贝。"""
    va = ValuationAnalysis(
        narrative="v1.x A5a multi-model cross-check (test)",
        industry_classification="白酒",
        active_models=[ValuationModel.PE, ValuationModel.DCF],
        pe_value=1500.0,
        dcf_base=1800.0,
        dcf_bull=2200.0,
        dcf_bear=1500.0,
        valuation_consistency="consistent",
    )
    return ResearchState(
        user_id="test",
        session_id="s",
        user_message="尽调",
        request_id="r",
        target_ts_code="600519.SH",
        client_total_aum=10_000_000.0,
        investment_objective="balanced",
        investment_horizon="medium_term",
        risk_tolerance="moderate",
        valuation_analysis=va,
    )


def _build_minimal_report_fixture(
    *,
    valuation_narrative: str = "LLM 占位 — 应被 state 覆盖",
) -> InvestmentDueDiligenceReport:
    """Minimal valid InvestmentDueDiligenceReport — 镜像 test_writer_post_process.py 风格。"""
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
            valuation_analysis=ValuationAnalysis(narrative=valuation_narrative),
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
        investment_recommendation=InvestmentRecommendation(
            narrative="LLM 建议综述",
            recommendation="recommend_buy",
            recommended_position_size_pct=10.0,
            recommended_holding_period="medium_term",
            recommended_entry_price_range=PriceRange(low=1500.0, high=1800.0),
            recommended_stop_loss_price=1400.0,
            estimated_target_price_range=PriceRange(low=2000.0, high=2200.0),
            position_management_conditions=["分批建仓"],
        ),
    )


def test_analyst_no_tool_results_skips_valuation_returns_none() -> None:
    """tool_results 空 → _maybe_compute_valuation_analysis 返 None,不破 step。"""
    llm = MagicMock()
    agent = Analyst(llm=llm)

    state = _make_minimal_state()
    va = agent._maybe_compute_valuation_analysis(state)  # noqa: SLF001
    assert va is None


def test_analyst_step_returns_state_update_without_valuation_when_tool_results_empty() -> None:
    """Analyst.step() — tool_results 空,state_update 不含 valuation_analysis key.

    保证 Path A 兼容:占位实现 return None 时,既有 e2e 不受影响。
    """
    llm = MagicMock()
    llm.chat = MagicMock(
        return_value=MagicMock(
            content='{"insights": []}',
            model="m",
            cost_cny=0.001,
        )
    )
    agent = Analyst(llm=llm)
    state = _make_minimal_state()

    result = agent.step(state)
    assert "insights" in result.state_update
    # tool_results 空 → _maybe_compute_valuation_analysis 返 None → state_update 不含 key
    assert "valuation_analysis" not in result.state_update


def test_writer_post_process_copies_valuation_analysis_when_present() -> None:
    """state.valuation_analysis is not None → report.financial_analysis.valuation_analysis 被替换。"""
    state = _make_state_with_precomputed_va()
    minimal_report = _build_minimal_report_fixture(
        valuation_narrative="LLM 占位 narrative — 应被 state 覆盖"
    )

    out = post_process_writer_output(state, minimal_report)

    # 被替换为 state.valuation_analysis (不是 LLM 占位)
    out_va = out.financial_analysis.valuation_analysis
    assert out_va.pe_value == 1500.0
    assert out_va.dcf_base == 1800.0
    assert out_va.industry_classification == "白酒"
    assert out_va.valuation_consistency == "consistent"
    assert out_va.active_models == [ValuationModel.PE, ValuationModel.DCF]
    # LLM 占位 narrative 已被覆盖
    assert out_va.narrative != "LLM 占位 narrative — 应被 state 覆盖"
    assert "multi-model cross-check" in out_va.narrative


def test_writer_post_process_no_valuation_analysis_keeps_llm_placeholder() -> None:
    """state.valuation_analysis is None → financial_analysis.valuation_analysis 保留 LLM 占位。"""
    state = ResearchState(
        user_id="t",
        session_id="s",
        user_message="m",
        request_id="r",
        target_ts_code="600519.SH",
        client_total_aum=10_000_000.0,
        investment_objective="balanced",
        investment_horizon="medium_term",
        risk_tolerance="moderate",
        valuation_analysis=None,  # 显式 None
    )

    minimal_report = _build_minimal_report_fixture(
        valuation_narrative="LLM 占位 narrative — 应保留"
    )
    original_va = minimal_report.financial_analysis.valuation_analysis

    out = post_process_writer_output(state, minimal_report)

    # 没替换 — 仍是 LLM 占位
    assert out.financial_analysis.valuation_analysis == original_va
    assert out.financial_analysis.valuation_analysis.narrative == "LLM 占位 narrative — 应保留"


# ---------------------------------------------------------------------------
# v1.x A5a follow-up #1: Analyst真 wire — tool_results 完整 → ValuationAnalysis 非 None
# ---------------------------------------------------------------------------


def test_analyst_complete_tool_results_yields_valuation_analysis() -> None:
    """完整 tool_results → _maybe_compute_valuation_analysis 真产 ValuationAnalysis.

    白酒 industry → PE + DCF active; daily_basic.pe=25 + pb=8 + total_mv 反推 eps/bvps/shares;
    pe_history.median_pe=28 作 industry_pe 可比 fallback;
    EBITDA 缺 (设 0) → 但白酒 industry mapping 不激活 EV-EBITDA,故无 skip 影响;
    DCF: forecast_growth=None + historical=空 → InsufficientDataForModelError → DCF skip
    剩 PE 真算: implied_price = 72 (eps) × (28 median+pe_avg avg)/2 ≈ legit number
    """
    llm = MagicMock()
    agent = Analyst(llm=llm)

    state = _make_state_with_complete_tool_results()
    va = agent._maybe_compute_valuation_analysis(state)  # noqa: SLF001

    assert va is not None
    assert isinstance(va, ValuationAnalysis)
    assert va.industry_classification == "白酒"
    # PE 真算成功 (eps>0 + industry_pe>0)
    assert va.pe_value is not None
    assert va.pe_value > 0
    # DCF 应该 skip (growth signal 缺): dcf_base = None
    assert va.dcf_base is None
    # active_models 仍是 router default (PE + DCF),DCF skip 不改 active_models
    assert ValuationModel.PE in va.active_models
    # narrative 是占位 (Writer 阶段会扩充)
    assert "multi-model cross-check" in va.narrative


def test_analyst_step_complete_tool_results_writes_valuation_to_state_update() -> None:
    """Analyst.step() 真 wire — 完整 tool_results → state_update 含 valuation_analysis."""
    llm = MagicMock()
    llm.chat = MagicMock(
        return_value=MagicMock(
            content='{"insights": []}',
            model="m",
            cost_cny=0.001,
        )
    )
    agent = Analyst(llm=llm)
    state = _make_state_with_complete_tool_results()

    result = agent.step(state)

    assert "insights" in result.state_update
    assert "valuation_analysis" in result.state_update
    va = result.state_update["valuation_analysis"]
    assert isinstance(va, ValuationAnalysis)
    assert va.pe_value is not None and va.pe_value > 0
    assert va.industry_classification == "白酒"


def test_writer_post_process_preserves_other_financial_fields_when_copying_va() -> None:
    """state.valuation_analysis 拷贝时,financial_analysis 其它字段必须保持原样。"""
    state = _make_state_with_precomputed_va()
    minimal_report = _build_minimal_report_fixture()

    out = post_process_writer_output(state, minimal_report)

    # financial_analysis 其它字段必须原样保留
    assert out.financial_analysis.narrative == minimal_report.financial_analysis.narrative
    assert (
        out.financial_analysis.profitability_analysis
        == minimal_report.financial_analysis.profitability_analysis
    )
    assert (
        out.financial_analysis.cash_flow_analysis
        == minimal_report.financial_analysis.cash_flow_analysis
    )
    # 其它 section 也完全不动
    assert out.target_overview == minimal_report.target_overview
    assert out.industry_analysis == minimal_report.industry_analysis
    assert out.risk_assessment == minimal_report.risk_assessment
