"""L0 — critic_subgraph builds, runs 6 scorers (v1.x), returns CriticReport."""

from typing import Any

import pytest
from app.agents.base import Agent
from app.agents.critic import Critic
from app.agents.critic_subagents.conciseness import ConcisenessScorer
from app.agents.critic_subagents.coverage import CoverageScorer
from app.agents.critic_subagents.factuality import FactualityScorer
from app.agents.critic_subagents.input_context_scorer import (
    InputContextAppropriatenessScorer,
)
from app.agents.critic_subagents.insight import InsightScorer
from app.agents.critic_subagents.structure import StructureScorer
from app.agents.schemas import CriticReport
from app.orchestration.critic_subgraph import build_critic_subgraph
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService


@pytest.mark.asyncio
async def test_critic_subgraph_runs_6_scorers(
    mock_llm_client: MockLLMClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """v1.x: subgraph orchestrates 6 scorers (plan_correctness dropped)."""
    monkeypatch.setenv("LLM_MODE", "mock")
    svc = LLMService(client=mock_llm_client)
    scorers: list[Agent] = [
        FactualityScorer(llm=svc),
        CoverageScorer(llm=svc),
        InsightScorer(llm=svc),
        StructureScorer(llm=svc),
        ConcisenessScorer(llm=svc),
        InputContextAppropriatenessScorer(llm=svc),  # 第 6 scorer (v0.8.4)
    ]
    critic = Critic(llm=svc, scorers=scorers)
    sub_app = build_critic_subgraph(critic)

    initial: dict[str, Any] = {
        "user_id": "u",
        "session_id": "s",
        "user_message": "m",
        "request_id": "req-test1234",
        "report_markdown": "# 测试研报",
        "insights": [],
        "plan": None,
        "tool_results": [],
        "collected_scores": [],
        # v0.8.4 — 6 structured input fields (needed by InputContextAppropriatenessScorer)
        "target_ts_code": "600519.SH",
        "client_total_aum": 10_000_000.0,
        "client_existing_position": None,
        "investment_objective": "balanced",
        "investment_horizon": "medium_term",
        "risk_tolerance": "moderate",
    }
    final = await sub_app.ainvoke(initial)
    assert "critic_report" in final
    report = final["critic_report"]
    assert isinstance(report, CriticReport)
    n = len(report.dimensions)
    assert n == 6, f"Expected 6 dimensions (v1.x — plan_correctness dropped), got {n}"

    # Verify input_context_appropriateness dimension is present
    ic_score = report.get_score("input_context_appropriateness")
    assert ic_score is not None, "input_context_appropriateness must be in critic_report.dimensions"
    assert 0.0 <= ic_score <= 10.0

    # Verify plan_correctness dimension is absent (v1.x)
    pc_score = report.get_score("plan_correctness")
    assert pc_score is None, "plan_correctness must NOT be in critic_report.dimensions in v1.x"
