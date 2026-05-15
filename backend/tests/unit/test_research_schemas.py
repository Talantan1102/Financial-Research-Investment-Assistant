"""L0 — research-mode I/O schemas."""

import pytest
from app.agents.schemas import (
    ChartSpec,
    CriticDimension,
    CriticDimensionScore,
    CriticReport,
    Insight,
    ResearchPlan,
    ResearchState,
    Subtask,
)
from pydantic import ValidationError


def test_subtask_minimal() -> None:
    s = Subtask(
        subtask_id="overview", description="x", required_tools=["get_stock_quote"], rationale="r"
    )
    assert s.subtask_id == "overview"


def test_research_plan_minimal() -> None:
    p = ResearchPlan(
        rationale="single subtask",
        subtasks=[
            Subtask(subtask_id="overview", description="x", required_tools=[], rationale="r")
        ],
    )
    assert len(p.subtasks) == 1


def test_research_plan_requires_subtasks() -> None:
    """v1.x — ResearchPlan requires ≥1 subtask (no more plan_id selector)."""
    with pytest.raises(ValidationError):
        ResearchPlan(rationale="r", subtasks=[])


def test_research_plan_rationale_max_length() -> None:
    """v1.x — rationale capped at 300 chars (was 200 in v0.8.5)."""
    with pytest.raises(ValidationError):
        ResearchPlan(
            rationale="x" * 301,
            subtasks=[
                Subtask(subtask_id="s", description="d", required_tools=[], rationale="r")
            ],
        )


def test_insight_confidence_levels() -> None:
    from typing import Literal

    confidence_levels: tuple[Literal["high", "medium", "low"], ...] = ("high", "medium", "low")
    for c in confidence_levels:
        Insight(subtask_id="s", finding="f", supporting_data=[], confidence=c)


def test_critic_dimension_score_range() -> None:
    s = CriticDimensionScore(
        dimension="factuality", score=8.5, evidence="cite x", sub_agent_request_id="r"
    )
    assert s.score == 8.5


def test_critic_dimension_score_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError):
        CriticDimensionScore(
            dimension="factuality", score=11.0, evidence="x", sub_agent_request_id="r"
        )


def test_critic_report_5_dims() -> None:
    dim_names: tuple[CriticDimension, ...] = (
        "factuality",
        "coverage",
        "insight",
        "structure",
        "conciseness",
    )
    dims = [
        CriticDimensionScore(dimension=d, score=8.0, evidence="e", sub_agent_request_id="r")
        for d in dim_names
    ]
    r = CriticReport(dimensions=dims, overall_score=8.0, summary_markdown="ok")
    assert len(r.dimensions) == 5


def test_chart_spec_minimal() -> None:
    c = ChartSpec(chart_id="c1", chart_type="line", title="t", data=[{"x": 1, "y": 2}])
    assert c.chart_type == "line"


def test_research_state_minimal() -> None:
    s = ResearchState(
        user_id="u",
        session_id="s",
        user_message="深度分析茅台",
        request_id="req-test1234",
    )
    assert s.plan is None
    assert s.tool_results == []
    assert s.report_markdown is None
    assert s.critic_report is None
