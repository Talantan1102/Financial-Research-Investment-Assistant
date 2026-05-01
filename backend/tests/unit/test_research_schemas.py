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
        subtasks=[
            Subtask(subtask_id="overview", description="x", required_tools=[], rationale="r")
        ],
        target_entity="600519.SH",
        research_style="comprehensive",
        reasoning="single subtask",
    )
    assert len(p.subtasks) == 1
    assert p.research_style == "comprehensive"


def test_research_plan_invalid_style_rejected() -> None:
    with pytest.raises(ValidationError):
        ResearchPlan(
            subtasks=[],
            target_entity="x",
            research_style="weekly",  # type: ignore[arg-type]
            reasoning="r",
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
