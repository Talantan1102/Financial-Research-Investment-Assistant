"""L0 — ChatAgent v0.9."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.agents.chat_agent import ChatAgent
from app.agents.schemas import Plan


@pytest.mark.asyncio
async def test_chat_agent_run_returns_sutoutput():
    graph = MagicMock()
    graph.ainvoke = AsyncMock(
        return_value={
            "user_id": "u",
            "session_id": "s",
            "user_message": "x",
            "request_id": "r",
            "trace_request_id": "r",
            "final_response": "hello!",
            "plan": Plan(direct_response=True, tool_calls=[], reasoning="direct").model_dump(),
            "escalate_offered": False,
        }
    )
    agent = ChatAgent(graph=graph)
    out = await agent.run("hi", request_id="r")
    assert out.response_text == "hello!"
    assert out.request_id == "r"


@pytest.mark.asyncio
async def test_chat_agent_exposes_escalate_flag():
    graph = MagicMock()
    graph.ainvoke = AsyncMock(
        return_value={
            "user_id": "u",
            "session_id": "s",
            "user_message": "x",
            "request_id": "r",
            "trace_request_id": "r",
            "final_response": "ok",
            "plan": Plan(
                direct_response=True,
                tool_calls=[],
                reasoning="escalate",
                escalate_offered=True,
                escalate_reason="deep req",
            ).model_dump(),
            "escalate_offered": True,
        }
    )
    agent = ChatAgent(graph=graph)
    out = await agent.run("hi", request_id="r")
    assert out.escalate_offered is True
