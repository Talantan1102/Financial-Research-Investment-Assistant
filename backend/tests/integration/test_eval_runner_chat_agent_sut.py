"""L1 — EvalRunner SUT swap: backward-compat (bare LLMService) + ChatAgent SUT.

Task 12 assertions:
1. Bare LLMService SUT → tool_correctness is None (Plan C backward compat)
2. ChatAgent SUT → tool_correctness is not None (ChatAgent invokes tools)

Both tests call run_one() synchronously.  The async SUT is bridged via
asyncio.run() inside EvalRunner.run_one (Pattern B).
"""

from __future__ import annotations

import contextlib
from typing import Any
from unittest.mock import MagicMock

from app.agents.chat_agent import ChatAgent
from app.agents.chat_planner import ChatPlanner
from app.agents.in_session_memory import InSessionMemory
from app.agents.responder import Responder
from app.orchestration.chat_graph import build_chat_graph
from app.services.eval_models import GoldenCase
from app.services.eval_recorder import EvalRecorder
from app.services.eval_runner import EvalRunner
from app.services.judge import Judge
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService
from app.services.tool_result_cache import ToolResultCache
from app.services.trace_service import TraceService
from app.tools.base import Tool
from app.tools.registry import ToolRegistry
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Stub tools (reuse pattern from test_chat_agent_e2e_mock.py)
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
        return {"ts_code": validated.ts_code, "price": 1820.5, "change_pct": 0.5, "volume": 12345.0}


class _StubFinancialsArgs(BaseModel):
    ts_code: str
    period: str = "latest"


class StubFinancialsTool(Tool):
    name = "get_financials"
    description = "Return revenue and net profit for a given A-share."
    args_schema = _StubFinancialsArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        validated = _StubFinancialsArgs.model_validate(args.model_dump())
        return {"ts_code": validated.ts_code, "revenue": 1e10, "net_profit": 2e9}


class _StubNewsArgs(BaseModel):
    ts_code: str | None = None
    n: int = 5
    days_back: int = 7


class StubNewsTool(Tool):
    name = "get_news"
    description = "Return recent news for a given A-share."
    args_schema = _StubNewsArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        return {"items": [{"title": "stub news", "url": "https://example.com"}]}


# ---------------------------------------------------------------------------
# Shared golden case factory
# ---------------------------------------------------------------------------


def _make_case(case_id: str) -> GoldenCase:
    return GoldenCase(
        case_id=case_id,
        category="single_tool_call",
        user_input="查一下 600519.SH 的股价",
        expected_behavior={"response_must_contain": ["600519", "股价"]},
        metadata={"added_by": "test", "added_at": "2026-05-01", "tags": []},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_llm_service_sut_tool_correctness_is_none(
    mock_llm_client: MockLLMClient,
    db_session,
) -> None:
    """Backward-compat: bare LLMService SUT → JudgeScores.tool_correctness is None."""
    trace = TraceService(session_factory=lambda: contextlib.nullcontext(db_session))
    recorder = EvalRecorder(session_factory=lambda: contextlib.nullcontext(db_session))

    sut_llm = LLMService(client=mock_llm_client, trace_service=trace)
    judge_llm = LLMService(client=mock_llm_client)
    judge = Judge(llm=judge_llm, judge_tier="balanced")

    runner = EvalRunner(sut=sut_llm, judge=judge, trace_service=trace, recorder=recorder)
    case = _make_case("llm-sut-compat")

    result = runner.run_one(case)

    assert result.scores.factuality is not None
    tc = result.scores.tool_correctness
    assert tc is None, f"Expected tool_correctness=None for bare LLMService SUT, got {tc}"


def test_chat_agent_sut_tool_correctness_is_not_none(
    mock_llm_client: MockLLMClient,
    db_session,
) -> None:
    """ChatAgent SUT: tool_calls passed to Judge → JudgeScores.tool_correctness is not None."""
    trace = TraceService(session_factory=lambda: contextlib.nullcontext(db_session))
    recorder = EvalRecorder(session_factory=lambda: contextlib.nullcontext(db_session))

    # Build ChatAgent stack (mirrors test_chat_agent_e2e_mock.py)
    svc = LLMService(client=mock_llm_client)
    registry = ToolRegistry()
    registry.register(StubQuoteTool())
    registry.register(StubFinancialsTool())
    registry.register(StubNewsTool())
    planner = ChatPlanner(llm=svc, registry=registry)
    responder = Responder(llm=svc)
    # Plan 1 signature: memory + cache required; use lightweight stubs for tests
    memory = InSessionMemory()
    cache = ToolResultCache(session_factory=MagicMock())
    graph = build_chat_graph(
        planner=planner, responder=responder, registry=registry, memory=memory, cache=cache
    )
    agent = ChatAgent(graph=graph)

    judge_llm = LLMService(client=mock_llm_client)
    judge = Judge(llm=judge_llm, judge_tier="balanced")

    runner = EvalRunner(sut=agent, judge=judge, trace_service=trace, recorder=recorder)
    case = _make_case("chat-agent-sut")

    result = runner.run_one(case)

    assert result.scores.factuality is not None
    tc = result.scores.tool_correctness
    assert tc is not None, "Expected tool_correctness to be scored for ChatAgent SUT, got None"
