"""L0 — ChatPlanner v0.9."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from app.agents.chat_planner import ChatPlanner
from app.agents.schemas import ChatState
from app.services.llm_response import LLMResponse
from app.services.llm_service import LLMService


def _make_llm_response(mock_response_json: str) -> LLMResponse:
    """Build a minimal valid LLMResponse with the given JSON as content."""
    return LLMResponse(
        content=mock_response_json,
        model="qwen-plus",
        tier="fast",
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
        cost_cny=0.0,
        latency_ms=100,
    )


def _make_llm(mock_response_json: str) -> LLMService:
    llm = MagicMock(spec=LLMService)
    llm.chat.return_value = _make_llm_response(mock_response_json)
    return llm


@pytest.mark.asyncio
async def test_planner_emits_parallel_tool_calls():
    llm = _make_llm(
        json.dumps(
            {
                "tool_calls": [
                    {
                        "tool_name": "get_quote",
                        "args": {"ts_code": "601398.SH"},
                        "rationale": "行情",
                    },
                    {
                        "tool_name": "get_financials",
                        "args": {"ts_code": "601398.SH"},
                        "rationale": "财务",
                    },
                ],
                "parallelizable": True,
                "direct_response": False,
                "escalate_offered": False,
                "reasoning": "用户问 ICBC 概览，需要行情和财务数据",
            }
        )
    )
    planner = ChatPlanner(llm=llm, available_tools=["get_quote", "get_financials"])
    state = ChatState(
        user_id="u",
        session_id="s",
        user_message="ICBC 概览",
        request_id="r",
        trace_request_id="r",
    )
    out = await planner.run(state)
    plan = out["plan"]
    assert len(plan.tool_calls) == 2
    assert plan.parallelizable is True
    assert plan.escalate_offered is False


@pytest.mark.asyncio
async def test_planner_emits_escalate_when_deep_intent_detected():
    llm = _make_llm(
        json.dumps(
            {
                "tool_calls": [],
                "parallelizable": False,
                "direct_response": True,
                "escalate_offered": True,
                "escalate_reason": "user 要求完整尽调报告",
                "reasoning": "用户要求深度分析，建议升级到研报模式",
            }
        )
    )
    planner = ChatPlanner(llm=llm, available_tools=[])
    state = ChatState(
        user_id="u",
        session_id="s",
        user_message="给我做一份 ICBC 完整尽调",
        request_id="r",
        trace_request_id="r",
    )
    out = await planner.run(state)
    assert out["plan"].escalate_offered is True


@pytest.mark.asyncio
async def test_planner_filters_unknown_tool_names(caplog):
    """A4 — LLM hallucinates `analyze_balance_sheet`; planner drops it."""
    llm = _make_llm(
        json.dumps(
            {
                "tool_calls": [
                    {"tool_name": "analyze_balance_sheet", "args": {}, "rationale": "hallucinated"},
                    {"tool_name": "get_quote", "args": {"ts_code": "X"}, "rationale": "行情"},
                ],
                "parallelizable": False,
                "direct_response": False,
                "escalate_offered": False,
                "reasoning": "需要查行情",
            }
        )
    )
    planner = ChatPlanner(llm=llm, available_tools=["get_quote"])
    state = ChatState(
        user_id="u",
        session_id="s",
        user_message="X",
        request_id="r",
        trace_request_id="r",
    )
    out = await planner.run(state)
    assert len(out["plan"].tool_calls) == 1
    assert out["plan"].tool_calls[0].tool_name == "get_quote"
