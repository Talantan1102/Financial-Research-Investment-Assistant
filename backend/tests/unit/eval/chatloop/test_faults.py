from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from app.agents.schemas import ToolResult
from app.chatloop.state import ChatLoopState
from app.services.llm_step import StepToolCall
from eval.chatloop.faults import (
    DeterministicBarrier,
    FaultInjectingHub,
    FaultPlan,
    TransportFaultPlan,
)


def _state() -> ChatLoopState:
    return ChatLoopState(
        user_id="eval-user",
        session_id="eval-session",
        request_id="eval-request",
        messages=[{"role": "user", "content": "检查权限"}],
    )


@pytest.mark.asyncio
async def test_timeout_fault_returns_declared_error_without_calling_inner() -> None:
    inner = Mock()
    inner.schemas_for_llm.return_value = [
        {"type": "function", "function": {"name": "permission_check"}}
    ]
    inner.dispatch = AsyncMock()
    hub = FaultInjectingHub(
        inner,
        [FaultPlan(target="permission_check", mode="timeout")],
    )
    call = StepToolCall(id="call-1", name="permission_check", arguments="{}")

    results = await hub.dispatch([call], _state())

    assert len(results) == 1
    assert results[0].success is False
    assert results[0].error_code == "timeout"
    assert results[0].tool_name == "permission_check"
    inner.dispatch.assert_not_awaited()
    assert hub.schemas_for_llm() == [{"type": "function", "function": {"name": "permission_check"}}]


@pytest.mark.asyncio
async def test_stale_fault_returns_declared_payload_without_calling_live_tool() -> None:
    inner = Mock()
    inner.schemas_for_llm.return_value = [
        {"type": "function", "function": {"name": "get_market_clock"}}
    ]
    inner.dispatch = AsyncMock(
        return_value=[
            ToolResult(
                tool_name="get_market_clock",
                args={},
                success=True,
                output={"phase": "continuous"},
                latency_ms=1,
            )
        ]
    )
    hub = FaultInjectingHub(
        inner,
        [
            FaultPlan(
                target="get_market_clock",
                mode="stale",
                payload={"output": {"phase": "midday_break"}},
            )
        ],
    )

    results = await hub.dispatch(
        [StepToolCall(id="clock-1", name="get_market_clock", arguments="{}")],
        _state(),
    )

    assert results[0].success is True
    assert results[0].output == {"phase": "midday_break"}
    assert results[0].tool_call_data == {
        "fault_injected": True,
        "fault_mode": "stale",
    }
    inner.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_mixed_live_and_stale_calls_preserve_original_result_order() -> None:
    inner = Mock()
    inner.schemas_for_llm.return_value = [
        {"type": "function", "function": {"name": name}}
        for name in ("live_a", "stale_b", "live_c", "stale_d")
    ]
    inner.dispatch = AsyncMock(
        return_value=[
            ToolResult(
                tool_name="live_a",
                args={"slot": "a"},
                success=True,
                output={"value": "live-a"},
                latency_ms=1,
            ),
            ToolResult(
                tool_name="live_c",
                args={"slot": "c"},
                success=True,
                output={"value": "live-c"},
                latency_ms=1,
            ),
        ]
    )
    hub = FaultInjectingHub(
        inner,
        [
            FaultPlan(target="stale_b", mode="stale", payload={"value": "stale-b"}),
            FaultPlan(target="stale_d", mode="stale", payload={"value": "stale-d"}),
        ],
    )
    calls = [
        StepToolCall(id="a", name="live_a", arguments='{"slot":"a"}'),
        StepToolCall(id="b", name="stale_b", arguments='{"slot":"b"}'),
        StepToolCall(id="c", name="live_c", arguments='{"slot":"c"}'),
        StepToolCall(id="d", name="stale_d", arguments='{"slot":"d"}'),
    ]

    results = await hub.dispatch(calls, _state())

    assert [item.tool_name for item in results] == ["live_a", "stale_b", "live_c", "stale_d"]
    assert [item.output for item in results] == [
        {"value": "live-a"},
        {"value": "stale-b"},
        {"value": "live-c"},
        {"value": "stale-d"},
    ]
    forwarded = inner.dispatch.await_args.args[0]
    assert [item.name for item in forwarded] == ["live_a", "live_c"]


def test_fault_target_that_is_not_a_registered_tool_fails_loudly() -> None:
    inner = Mock()
    inner.schemas_for_llm.return_value = [
        {"type": "function", "function": {"name": "get_market_quote"}}
    ]

    with pytest.raises(ValueError, match="unsupported fault target.*market_data"):
        FaultInjectingHub(inner, [FaultPlan(target="market_data", mode="stale")])


def test_generic_decorator_rejects_conflicts_that_need_scenario_specific_hooks() -> None:
    inner = Mock()
    inner.schemas_for_llm.return_value = [
        {"type": "function", "function": {"name": "manage_watchlist"}}
    ]

    with pytest.raises(ValueError, match="scenario-specific fault mode.*conflict"):
        FaultInjectingHub(inner, [FaultPlan(target="manage_watchlist", mode="conflict")])


def test_response_lost_after_commit_requires_observation_before_retry() -> None:
    plan = TransportFaultPlan(response_lost_after_commit=True)

    assert plan.retry_policy == "observe_before_retry"


@pytest.mark.asyncio
async def test_barrier_records_a_reproducible_pause_and_release() -> None:
    barrier = DeterministicBarrier()
    task = asyncio.create_task(barrier.pause("cancel-read"))

    await barrier.wait_until_reached("cancel-read")
    barrier.release("cancel-read")
    await task

    assert barrier.timeline == [
        {"event": "reached", "label": "cancel-read"},
        {"event": "released", "label": "cancel-read"},
    ]
