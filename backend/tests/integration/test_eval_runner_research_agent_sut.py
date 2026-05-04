"""L1 — EvalRunner with ResearchAgent SUT, verifying report_markdown_quality emitted.

Task 12 (v0.5) assertions:
1. ResearchAgent SUT → JudgeScores.report_markdown_quality is not None
   (because response_text is the full research report markdown, ≥ 5-dim judge path)
2. ResearchAgent SUT → JudgeScores.tool_correctness is not None
   (because ResearchAgent produces non-empty tool_calls)

EvalRunner passes report_markdown=sut_output.response_text always; the judge
switches to the 5-dim template and the fixture returns a non-null score.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
from app.agents.data_collector import DataCollector
from app.agents.research_agent import ResearchAgent
from app.agents.research_planner import ResearchPlanner
from app.agents.writer import Writer
from app.orchestration.research_graph import build_research_graph
from app.services.eval_models import GoldenCase
from app.services.eval_recorder import EvalRecorder
from app.services.eval_runner import EvalRunner
from app.services.judge import Judge
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService
from app.services.trace_service import TraceService
from app.tools.base import Tool
from app.tools.registry import ToolRegistry
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Stub tools (mirrors test_research_agent_e2e_mock.py)
# ---------------------------------------------------------------------------


class _StubQuoteArgs(BaseModel):
    ts_code: str


class StubQuoteTool(Tool):
    """Stub for get_stock_quote — returns fixed price without I/O."""

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
    """Stub for get_financials — returns fixed financials without I/O."""

    name = "get_financials"
    description = "Return revenue and net profit for a given A-share."
    args_schema = _StubFinancialsArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        validated = _StubFinancialsArgs.model_validate(args.model_dump())
        return {"ts_code": validated.ts_code, "revenue": 1e10, "net_profit": 2e9}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_research_agent(svc: LLMService) -> ResearchAgent:
    """Assemble the full ResearchAgent stack with stub tools."""
    registry = ToolRegistry()
    registry.register(StubQuoteTool())
    registry.register(StubFinancialsTool())

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
    return ResearchAgent(graph=graph)


def _make_research_case() -> GoldenCase:
    return GoldenCase(
        case_id="research-agent-sut-v05",
        category="single_tool_call",
        user_input="生成茅台 600519.SH 的研报",
        expected_behavior={"response_must_contain": ["茅台", "股价"]},
        metadata={"added_by": "test", "added_at": "2026-05-01", "tags": []},
        expected_topics=["价格", "财务健康"],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_research_agent_sut_report_markdown_quality_not_none(
    mock_llm_client: MockLLMClient,
    tmp_eval_db: Path,
) -> None:
    """ResearchAgent SUT path: report_markdown_quality and tool_correctness both scored."""
    trace = TraceService(db_path=tmp_eval_db)
    trace.init_schema()
    recorder = EvalRecorder(db_path=tmp_eval_db)
    recorder.init_schema()

    svc = LLMService(client=mock_llm_client)
    agent = _build_research_agent(svc)

    judge_llm = LLMService(client=mock_llm_client)
    judge = Judge(llm=judge_llm, judge_tier="balanced")

    runner = EvalRunner(sut=agent, judge=judge, trace_service=trace, recorder=recorder)
    case = _make_research_case()

    result = runner.run_one(case)

    # tool_correctness: ResearchAgent always produces non-empty tool_calls
    tc = result.scores.tool_correctness
    assert tc is not None, "Expected tool_correctness to be scored for ResearchAgent SUT, got None"

    # report_markdown_quality: EvalRunner passes response_text as report_markdown →
    # 5-dim judge fixture → non-null score
    rmq = result.scores.report_markdown_quality
    assert rmq is not None, "report_markdown_quality should be scored for ResearchAgent SUT"
    assert 0.0 <= rmq <= 10.0, f"report_markdown_quality out of range [0,10]: {rmq}"
