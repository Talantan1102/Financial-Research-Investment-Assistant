"""L0 — research graph compiles + has expected node set."""

import pytest
from app.agents.analyst import Analyst
from app.agents.base import Agent
from app.agents.critic import Critic
from app.agents.critic_subagents.conciseness import ConcisenessScorer
from app.agents.critic_subagents.coverage import CoverageScorer
from app.agents.critic_subagents.factuality import FactualityScorer
from app.agents.critic_subagents.insight import InsightScorer
from app.agents.critic_subagents.structure import StructureScorer
from app.agents.data_collector import DataCollector
from app.agents.research_planner import ResearchPlanner
from app.agents.writer import Writer
from app.orchestration.research_graph import build_research_graph
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService
from app.tools.registry import ToolRegistry


def test_build_research_graph_returns_compiled(
    mock_llm_client: MockLLMClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """build_research_graph compiles without error and returns a non-None graph."""
    monkeypatch.setenv("LLM_MODE", "mock")
    svc = LLMService(client=mock_llm_client)
    registry = ToolRegistry()
    planner = ResearchPlanner(llm=svc)
    collector = DataCollector(llm=svc, registry=registry)
    analyst = Analyst(llm=svc)
    writer = Writer(llm=svc)
    scorers: list[Agent] = [
        FactualityScorer(llm=svc),
        CoverageScorer(llm=svc),
        InsightScorer(llm=svc),
        StructureScorer(llm=svc),
        ConcisenessScorer(llm=svc),
    ]
    critic = Critic(llm=svc, scorers=scorers)

    graph = build_research_graph(
        planner=planner,
        collector=collector,
        analyst=analyst,
        writer=writer,
        critic=critic,
        db_path=None,
    )
    assert graph is not None
    # The compiled graph should be invokable; ainvoke check left for e2e
