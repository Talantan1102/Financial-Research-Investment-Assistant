"""ResearchPlan v1.x schema — drop plan_id, require subtasks."""
from __future__ import annotations

import pytest
from app.agents.schemas import ResearchPlan, Subtask
from pydantic import ValidationError


def test_research_plan_no_plan_id_field() -> None:
    """v1.x: plan_id removed."""
    assert "plan_id" not in ResearchPlan.model_fields


def test_research_plan_requires_subtasks() -> None:
    """LLM must emit ≥1 subtask (min_length=1)."""
    with pytest.raises(ValidationError):
        ResearchPlan(rationale="t", subtasks=[])


def test_research_plan_accepts_valid_input() -> None:
    p = ResearchPlan(
        rationale="balanced strategy",
        subtasks=[Subtask(
            subtask_id="s1",
            description="财务全景",
            required_tools=["get_financials"],
            rationale="basics",
        )],
    )
    assert p.rationale == "balanced strategy"
    assert len(p.subtasks) == 1


def test_research_plan_extra_ignore() -> None:
    """extra fields silently dropped (LLM hallucinate-tolerant)."""
    p = ResearchPlan.model_validate({
        "rationale": "x",
        "subtasks": [{"subtask_id": "s1", "description": "d", "required_tools": [], "rationale": "r"}],
        "extra_field": "should be ignored",
    })
    assert not hasattr(p, "extra_field")


def test_research_plan_rationale_max_length() -> None:
    """rationale max_length is 300 in v1.x (was 200 in v0.8.5)."""
    with pytest.raises(ValidationError):
        ResearchPlan(
            rationale="x" * 301,
            subtasks=[Subtask(subtask_id="s1", description="d", required_tools=[], rationale="r")],
        )
