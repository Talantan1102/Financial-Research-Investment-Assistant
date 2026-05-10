"""L0 — Responder v0.9."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from app.agents.responder import Responder
from app.agents.schemas import ChatState, Plan, ToolResult
from app.services.llm_response import LLMResponse
from app.services.llm_service import LLMService


def _make_llm_response(content: str) -> LLMResponse:
    """Build LLMResponse with correct fields per llm_response.py schema."""
    return LLMResponse(
        content=content,
        tier="fast",
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
        cost_cny=0.001,
        latency_ms=100,
        model="qwen-plus",
    )


def _llm(content: str) -> LLMService:
    m = MagicMock(spec=LLMService)
    m.chat.return_value = _make_llm_response(content)
    return m


@pytest.mark.asyncio
async def test_responder_with_no_tools_uses_history():
    llm = _llm("当前股价 6.45 元")
    r = Responder(llm=llm)
    state = ChatState(
        user_id="u",
        session_id="s",
        user_message="ICBC 现价",
        request_id="r",
        trace_request_id="r",
        plan=Plan(direct_response=True, tool_calls=[], reasoning="直接回答"),
        tool_results=[],
    )
    out = await r.run(state)
    assert "6.45" in out["final_response"]


@pytest.mark.asyncio
async def test_responder_projects_tool_results():
    llm = _llm("ICBC 现价 6.45 元,涨幅 0.15%")
    r = Responder(llm=llm)
    state = ChatState(
        user_id="u",
        session_id="s",
        user_message="X",
        request_id="r",
        trace_request_id="r",
        tool_results=[
            ToolResult(
                tool_name="get_quote",
                args={"ts_code": "601398.SH"},
                output={"price": 6.45, "change_pct": 0.15, "volume": 145000.0},
                success=True,
                latency_ms=50,
            ),
        ],
    )
    out = await r.run(state)
    # responder must include tool result text in prompt (kwargs-style or positional)
    prompt_arg = llm.chat.call_args.kwargs.get("prompt") or llm.chat.call_args.args[0]
    assert "get_quote" in prompt_arg
    assert "6.45" in prompt_arg
    assert "final_response" in out


@pytest.mark.asyncio
async def test_responder_tool_error_softanswer():
    """C2 — failed tool result -> responder explains in soft answer."""
    llm = _llm("抱歉,获取 ICBC 行情时出现问题,可稍后再试")
    r = Responder(llm=llm)
    state = ChatState(
        user_id="u",
        session_id="s",
        user_message="ICBC 现价",
        request_id="r",
        trace_request_id="r",
        tool_results=[
            ToolResult(
                tool_name="get_quote",
                args={},
                output=None,
                success=False,
                error="upstream timeout",
                latency_ms=10,
            ),
        ],
    )
    out = await r.run(state)
    prompt_arg = llm.chat.call_args.kwargs.get("prompt") or llm.chat.call_args.args[0]
    assert "error" in prompt_arg.lower() or "失败" in prompt_arg or "timeout" in prompt_arg
    assert "抱歉" in out["final_response"] or "稍后" in out["final_response"]
