"""L0 — v1.x A5b debate schema invariants."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_advocate_output_required_fields() -> None:
    from app.agents.debate_schemas import AdvocateOutput

    out = AdvocateOutput(
        arguments=["论据 1", "论据 2", "论据 3"],
        strongest_argument="最强论据",
        rebut_targets=[],
        confidence="high",
    )
    assert out.arguments == ["论据 1", "论据 2", "论据 3"]
    assert out.confidence == "high"
    assert out.rebut_targets == []


def test_advocate_output_min_3_arguments() -> None:
    from app.agents.debate_schemas import AdvocateOutput

    with pytest.raises(ValidationError):
        AdvocateOutput(
            arguments=["论据 1", "论据 2"],
            strongest_argument="x",
            confidence="high",
        )


def test_advocate_output_max_5_arguments() -> None:
    from app.agents.debate_schemas import AdvocateOutput

    with pytest.raises(ValidationError):
        AdvocateOutput(
            arguments=["1", "2", "3", "4", "5", "6"],
            strongest_argument="x",
            confidence="high",
        )


def test_advocate_output_strongest_max_length_300() -> None:
    from app.agents.debate_schemas import AdvocateOutput

    with pytest.raises(ValidationError):
        AdvocateOutput(
            arguments=["1", "2", "3"],
            strongest_argument="x" * 301,
            confidence="high",
        )


def test_advocate_output_frozen() -> None:
    """frozen=True → mutation 抛 ValidationError."""
    from app.agents.debate_schemas import AdvocateOutput

    out = AdvocateOutput(arguments=["1", "2", "3"], strongest_argument="x", confidence="high")
    with pytest.raises(ValidationError):
        out.confidence = "low"


def test_debate_trace_default_none_partial() -> None:
    from app.agents.debate_schemas import DebateTrace

    tr = DebateTrace(total_cost_cny=0.0, total_latency_ms=0, rounds_completed=0)
    assert tr.bull_v1 is None
    assert tr.bear_v1 is None
    assert tr.bull_v2 is None
    assert tr.bear_v2 is None


def test_debate_trace_rounds_bounded_0_to_2() -> None:
    from app.agents.debate_schemas import DebateTrace

    with pytest.raises(ValidationError):
        DebateTrace(total_cost_cny=0.0, total_latency_ms=0, rounds_completed=3)
    with pytest.raises(ValidationError):
        DebateTrace(total_cost_cny=0.0, total_latency_ms=0, rounds_completed=-1)


def test_investment_recommendation_v1x_a5b_new_fields() -> None:
    from app.agents.investment_dd_schema import InvestmentRecommendation, PriceRange

    rec = InvestmentRecommendation(
        recommendation="recommend_hold",
        recommended_position_size_pct=5.0,
        narrative="x",
        recommended_holding_period="medium_term",
        recommended_entry_price_range=PriceRange(low=10.0, high=20.0),
        recommended_stop_loss_price=9.0,
        estimated_target_price_range=PriceRange(low=18.0, high=25.0),
        position_management_conditions=[],
        evidence=[],
    )
    assert rec.bull_case == []
    assert rec.bear_case == []
    assert rec.strongest_bull_point is None
    assert rec.strongest_bear_point is None


def test_research_state_v1x_a5b_debate_trace_field() -> None:
    from app.agents.schemas import ResearchState

    state = ResearchState(user_id="u", session_id="s", user_message="m", request_id="r")
    assert state.debate_trace is None


def test_critic_dimension_v1x_a5b_adds_dialectical_balance() -> None:
    from app.agents.schemas import CriticDimensionScore

    score = CriticDimensionScore(
        dimension="dialectical_balance",
        score=9.0,
        evidence="narrative 双向论证",
        sub_agent_request_id="req-001",
    )
    assert score.dimension == "dialectical_balance"


# ---------------------------------------------------------------------------
# C62 regression: format_valuation_block SSOT + _SOP_TEXT export
# ---------------------------------------------------------------------------


def test_format_valuation_block_bull_includes_dcf_bull() -> None:
    """C62: bull side should include dcf_bull value."""
    from app.agents.debate_schemas import format_valuation_block
    from app.agents.investment_dd_schema import ValuationAnalysis
    from app.agents.schemas import ResearchState

    va = ValuationAnalysis(
        narrative="x",
        pe_value=1500.0,
        dcf_base=1400.0,
        dcf_bull=1700.0,
        dcf_bear=1100.0,
    )
    state = ResearchState(
        user_id="u", session_id="s", user_message="m", request_id="r", valuation_analysis=va
    )
    block = format_valuation_block(state, side="bull")
    assert "DCF bull: 1,700.00" in block
    assert "DCF bear: 1,100.00" in block  # bull side also shows bear for comparison
    assert "PE 理论价: 1,500.00" in block


def test_format_valuation_block_bear_highlights_severity() -> None:
    """C62: bear side should include SEVERE warning when consistency is severe."""
    from app.agents.debate_schemas import format_valuation_block
    from app.agents.investment_dd_schema import ValuationAnalysis
    from app.agents.schemas import ResearchState

    va = ValuationAnalysis(
        narrative="x",
        pe_value=1500.0,
        dcf_bear=900.0,
        valuation_consistency="severe",
    )
    state = ResearchState(
        user_id="u", session_id="s", user_message="m", request_id="r", valuation_analysis=va
    )
    block = format_valuation_block(state, side="bear")
    assert "SEVERE" in block
    assert "DCF bear: 900.00" in block


def test_format_valuation_block_returns_empty_for_none_analysis() -> None:
    """C62: when valuation_analysis is None, returns empty string."""
    from app.agents.debate_schemas import format_valuation_block
    from app.agents.schemas import ResearchState

    state = ResearchState(user_id="u", session_id="s", user_message="m", request_id="r")
    assert format_valuation_block(state, side="bull") == ""
    assert format_valuation_block(state, side="bear") == ""


def test_sop_text_is_single_ssot_shared_between_analyst_and_writer() -> None:
    """C62: analyst._SOP_TEXT and writer._SOP_TEXT must be the same object as
    financial_research._SOP_TEXT (single source of truth)."""
    from app.agents import analyst as analyst_mod
    from app.agents import writer as writer_mod
    from app.skills.financial_research import _SOP_TEXT as _PKG_SOP

    assert analyst_mod._SOP_TEXT is _PKG_SOP, (
        "C62: analyst._SOP_TEXT must be the same object as financial_research._SOP_TEXT"
    )
    assert writer_mod._SOP_TEXT is _PKG_SOP, (
        "C62: writer._SOP_TEXT must be the same object as financial_research._SOP_TEXT"
    )
