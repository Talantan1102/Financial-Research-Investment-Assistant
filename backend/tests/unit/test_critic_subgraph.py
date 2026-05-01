"""L0 — critic_subgraph builds, runs 5 scorers, returns CriticReport."""

from typing import Any

import pytest
from app.agents.base import Agent
from app.agents.critic import Critic
from app.agents.critic_subagents.conciseness import ConcisenessScorer
from app.agents.critic_subagents.coverage import CoverageScorer
from app.agents.critic_subagents.factuality import FactualityScorer
from app.agents.critic_subagents.insight import InsightScorer
from app.agents.critic_subagents.structure import StructureScorer
from app.agents.schemas import CriticReport
from app.orchestration.critic_subgraph import build_critic_subgraph
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService


@pytest.mark.asyncio
async def test_critic_subgraph_runs_5_scorers(
    mock_llm_client: MockLLMClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    svc = LLMService(client=mock_llm_client)
    scorers: list[Agent] = [
        FactualityScorer(llm=svc),
        CoverageScorer(llm=svc),
        InsightScorer(llm=svc),
        StructureScorer(llm=svc),
        ConcisenessScorer(llm=svc),
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
    }
    final = await sub_app.ainvoke(initial)
    assert "critic_report" in final
    report = final["critic_report"]
    assert isinstance(report, CriticReport)
    n = len(report.dimensions)
    assert n == 5
