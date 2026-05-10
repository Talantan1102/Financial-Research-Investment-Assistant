"""L0 — tool_node execute_script branch."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.agents.schemas import ChatState, Plan, SkillScriptCall
from app.orchestration.nodes import tool_node
from app.skills.script_schemas import (
    SkillExecutionError,
    SkillExecutionResult,
)


@pytest.fixture
def state_with_script_call():
    return ChatState(
        user_id="u",
        session_id="s",
        user_message="算 DCF",
        request_id="r",
        trace_request_id="r",
        plan=Plan(
            direct_response=False,
            tool_calls=[],
            reasoning="r",
            script_calls=[
                SkillScriptCall(
                    skill="financial_analysis",
                    script="scripts/calculate_dcf.py",
                    args={"wacc": 0.08},
                ),
            ],
        ),
    )


@pytest.fixture
def mock_executor():
    ex = MagicMock()
    ex.execute = AsyncMock(
        return_value=SkillExecutionResult(
            ok=True,
            stdout_json={"enterprise_value": 12000.0, "equity_value": 9500.0},
            stderr_text="",
            exit_code=0,
            elapsed_s=2.4,
            skill_name="financial_analysis",
            script_path="scripts/calculate_dcf.py",
        )
    )
    return ex


@pytest.mark.asyncio
async def test_tool_node_dispatches_script_call(state_with_script_call, mock_executor):
    sse_emit = MagicMock()
    out = await tool_node(
        state_with_script_call,
        registry=MagicMock(),
        cache=AsyncMock(),
        skill_executor=mock_executor,
        sse_emit=sse_emit,
    )
    tool_results = out["tool_results"]
    assert len(tool_results) == 1
    r = tool_results[0]
    assert r.tool_name == "skill_script"
    assert r.success is True
    assert r.output["enterprise_value"] == 12000.0


@pytest.mark.asyncio
async def test_tool_node_emits_skill_execute_sse_events(state_with_script_call, mock_executor):
    sse_emit = MagicMock()
    await tool_node(
        state_with_script_call,
        registry=MagicMock(),
        cache=AsyncMock(),
        skill_executor=mock_executor,
        sse_emit=sse_emit,
    )
    events = [c.args[0] for c in sse_emit.call_args_list]
    event_types = [e.get("event") for e in events]
    assert "skill_execute_start" in event_types
    assert "skill_execute_end" in event_types


@pytest.mark.asyncio
async def test_tool_node_failed_script_emits_error_event(state_with_script_call):
    failing_ex = MagicMock()
    failing_ex.execute = AsyncMock(
        return_value=SkillExecutionResult(
            ok=False,
            stdout_json=None,
            stderr_text="fail!",
            exit_code=2,
            elapsed_s=0.5,
            skill_name="financial_analysis",
            script_path="scripts/calculate_dcf.py",
            error=SkillExecutionError(
                kind="non_zero_exit",
                message="exit code 2",
            ),
        )
    )
    sse_emit = MagicMock()
    out = await tool_node(
        state_with_script_call,
        registry=MagicMock(),
        cache=AsyncMock(),
        skill_executor=failing_ex,
        sse_emit=sse_emit,
    )
    r = out["tool_results"][0]
    assert r.success is False
    assert r.error and "non_zero_exit" in r.error
    event_types = [c.args[0].get("event") for c in sse_emit.call_args_list]
    assert "skill_execute_error" in event_types
