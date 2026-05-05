"""L0 — 5 Critic sub-agents prompt construction + score parsing."""

import pytest
from app.agents.critic_subagents.conciseness import ConcisenessScorer
from app.agents.critic_subagents.coverage import CoverageScorer
from app.agents.critic_subagents.factuality import FactualityScorer
from app.agents.critic_subagents.insight import InsightScorer
from app.agents.critic_subagents.structure import StructureScorer
from app.agents.schemas import (
    CriticDimensionScore,
    Insight,
    ResearchPlan,
    ResearchState,
    Subtask,
)
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService


def _state_with_report() -> ResearchState:
    return ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="req-test1234",
        report_markdown="# 茅台研报\n\n股价 1820.5。",
        insights=[
            Insight(subtask_id="overview", finding="x", supporting_data=[], confidence="high")
        ],
        plan=ResearchPlan(
            plan_id="balanced",
            rationale="default test plan",
            subtasks=[
                Subtask(subtask_id="overview", description="d", required_tools=[], rationale="r")
            ],
            target_entity="600519.SH",
            research_style="comprehensive",
            reasoning="r",
        ),
    )


@pytest.mark.parametrize(
    "ScorerCls,dim",
    [
        (FactualityScorer, "factuality"),
        (CoverageScorer, "coverage"),
        (InsightScorer, "insight"),
        (StructureScorer, "structure"),
        (ConcisenessScorer, "conciseness"),
    ],
)
def test_scorer_returns_dimension_score(
    ScorerCls: type, dim: str, mock_llm_client: MockLLMClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    svc = LLMService(client=mock_llm_client)
    scorer = ScorerCls(llm=svc)

    state = _state_with_report()
    sr = scorer.step(state)

    score = sr.state_update[f"{dim}_score"]
    assert isinstance(score, CriticDimensionScore)
    assert score.dimension == dim
    in_range = 0.0 <= score.score <= 10.0
    assert in_range
