"""L1 integration — ResearchAgent end-to-end with full mock stack.

Exercises the full research graph path:
  research_planner_node → data_collector_node → analyst_node
  → writer_node → critic_node (5 parallel scorers)

Assertions:
- output.response_text is non-empty (Writer fixture returns markdown >50 chars)
- output.tool_calls has >= 2 entries (plan fixture has 2 subtasks, one tool each)
- tool_call names include both get_stock_quote and get_financials

MockLLMClient fixture coverage (from agent_decisions.yaml):
- "^你是金融研究助手 research_planner" → returns ResearchPlan JSON with 2 subtasks
- "^你是金融研究助手 analyst"          → returns 2 insights JSON
- "^你是金融研究助手 writer"           → returns report_markdown + chart_specs JSON
- "^你是金融研究助手 critic_"          → returns scorer JSON (5 × parallel)

Stub tools:
  StubQuoteTool (get_stock_quote) and StubFinancialsTool (get_financials) are
  registered so DataCollector can execute the plan without touching real data.
  Names match what the research_planner fixture returns in required_tools.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.agents.analyst import Analyst
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
from app.agents.data_collector import DataCollector
from app.agents.research_agent import ResearchAgent
from app.agents.research_planner import ResearchPlanner
from app.agents.writer import Writer
from app.orchestration.research_graph import build_research_graph
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService
from app.tools.base import Tool
from app.tools.registry import ToolRegistry
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Stub tools — avoid real data dependencies in L1 tests
# ---------------------------------------------------------------------------


class _StubQuoteArgs(BaseModel):
    ts_code: str


class StubQuoteTool(Tool):
    """Drop-in replacement for StockQuoteTool — returns a fixed quote dict."""

    name = "get_stock_quote"
    description = "Return the latest daily price for a given A-share."
    args_schema = _StubQuoteArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        validated = _StubQuoteArgs.model_validate(args.model_dump())
        return {
            "ts_code": validated.ts_code,
            "price": 1820.5,
            "change_pct": 0.5,
            "volume": 12345.0,
        }


class _StubFinancialsArgs(BaseModel):
    ts_code: str
    period: str = "latest"


class StubFinancialsTool(Tool):
    """Stub for get_financials — returns a fixed financials dict."""

    name = "get_financials"
    description = "Return revenue and net profit for a given A-share."
    args_schema = _StubFinancialsArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        validated = _StubFinancialsArgs.model_validate(args.model_dump())
        return {
            "ts_code": validated.ts_code,
            "revenue": 1e10,
            "net_profit": 2e9,
        }


# ---------------------------------------------------------------------------
# E2E test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_research_agent_e2e_full_pipeline(mock_llm_client: MockLLMClient) -> None:
    """Full research graph run: planner → collector → analyst → writer → critic."""
    svc = LLMService(client=mock_llm_client)

    # Register stub tools matching the research_planner fixture's required_tools
    registry = ToolRegistry()
    registry.register(StubQuoteTool())
    registry.register(StubFinancialsTool())

    # Assemble all agents
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
        InputContextAppropriatenessScorer(llm=svc),  # 第 6 scorer (v0.8.4)
        ValuationConsistencyScorer(llm=svc),  # 第 7 scorer (v1.x A5a)
        # v1.x: PlanCorrectnessScorer removed (Task 1.5).
    ]
    critic = Critic(llm=svc, scorers=scorers)

    # Build graph without checkpointer (pure in-memory, stateless for eval)
    graph = build_research_graph(
        planner=planner,
        collector=collector,
        analyst=analyst,
        writer=writer,
        critic=critic,
        db_path=None,
    )
    agent = ResearchAgent(graph=graph)

    # Execute
    output = await agent.run(
        user_input="生成茅台 600519.SH 的研报",
        request_id="req-research-e2e-test",
    )

    # Assertions
    assert output.request_id == "req-research-e2e-test"

    assert output.response_text, "response_text should be non-empty"
    assert len(output.response_text) > 50, "Writer fixture should produce >50 chars"

    n_calls = len(output.tool_calls)
    assert n_calls >= 2, f"Expected >=2 tool_calls (one per subtask), got {output.tool_calls}"

    tool_names = [tc.tool_name for tc in output.tool_calls]
    # v0.8.5: balanced plan_registry 4 subtasks 不含 get_stock_quote (研报场景不需实时报价).
    # 但应含 get_financials (financial_health subtask).
    assert "get_financials" in tool_names, f"get_financials missing from {tool_names}"
