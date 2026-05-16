"""L0 — critic_subgraph builds, runs 7 scorers (v1.x A5a), returns CriticReport."""

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
from app.agents.critic_subagents.valuation_consistency import ValuationConsistencyScorer
from app.agents.schemas import CriticReport
from app.orchestration.critic_subgraph import build_critic_subgraph
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService


@pytest.mark.asyncio
async def test_critic_subgraph_runs_7_scorers(
    mock_llm_client: MockLLMClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """v1.x A5a: subgraph orchestrates 7 scorers (plan_correctness dropped, valuation_consistency added)."""
    monkeypatch.setenv("LLM_MODE", "mock")
    svc = LLMService(client=mock_llm_client)
    scorers: list[Agent] = [
        FactualityScorer(llm=svc),
        CoverageScorer(llm=svc),
        InsightScorer(llm=svc),
        StructureScorer(llm=svc),
        ConcisenessScorer(llm=svc),
        InputContextAppropriatenessScorer(llm=svc),  # 第 6 scorer (v0.8.4)
        ValuationConsistencyScorer(llm=svc),  # 第 7 scorer (v1.x A5a)
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
        # v1.x A5a — valuation_analysis None → single-lens skip path → 10.0
        "valuation_analysis": None,
    }
    final = await sub_app.ainvoke(initial)
    assert "critic_report" in final
    report = final["critic_report"]
    assert isinstance(report, CriticReport)
    n = len(report.dimensions)
    assert n == 7, f"Expected 7 dimensions (v1.x A5a — valuation_consistency added), got {n}"

    # Verify input_context_appropriateness dimension is present
    ic_score = report.get_score("input_context_appropriateness")
    assert ic_score is not None, "input_context_appropriateness must be in critic_report.dimensions"
    assert 0.0 <= ic_score <= 10.0

    # Verify valuation_consistency dimension is present (v1.x A5a 第 7 维)
    vc_score = report.get_score("valuation_consistency")
    assert vc_score is not None, "valuation_consistency must be in critic_report.dimensions"
    assert 0.0 <= vc_score <= 10.0
    # valuation_analysis=None → skip path returns 10.0
    assert vc_score == 10.0, f"single-lens skip should yield 10.0, got {vc_score}"

    # Verify plan_correctness dimension is absent (v1.x): negative test —
    # CriticReport.get_score is typed to the 7-dim Literal post-v1.x A5a;
    # asking about a removed dim is the whole point of this assertion.
    pc_score = report.get_score("plan_correctness")  # type: ignore[arg-type]
    assert pc_score is None, "plan_correctness must NOT be in critic_report.dimensions in v1.x"
