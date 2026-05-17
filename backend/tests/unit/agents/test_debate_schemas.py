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
        out.confidence = "low"  # type: ignore[misc]


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
