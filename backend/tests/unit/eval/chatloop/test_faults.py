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
    FaultMode,
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
async def test_mixed_live_stale_and_conflict_calls_preserve_original_result_order() -> None:
    inner = Mock()
    inner.schemas_for_llm.return_value = [
        {"type": "function", "function": {"name": name}}
        for name in ("live_a", "stale_b", "manage_watchlist", "live_c", "stale_d")
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
                tool_name="manage_watchlist",
                args={"action": "add", "ts_code": "000063.SZ"},
                success=True,
                output={"created": False},
                latency_ms=2,
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
            FaultPlan(
                target="manage_watchlist",
                mode="conflict",
                payload={"kind": "duplicate_add", "same_payload": True},
            ),
            FaultPlan(target="stale_d", mode="stale", payload={"value": "stale-d"}),
        ],
    )
    calls = [
        StepToolCall(id="a", name="live_a", arguments='{"slot":"a"}'),
        StepToolCall(id="b", name="stale_b", arguments='{"slot":"b"}'),
        StepToolCall(
            id="watchlist",
            name="manage_watchlist",
            arguments='{"action":"add","ts_code":"000063.SZ"}',
        ),
        StepToolCall(id="c", name="live_c", arguments='{"slot":"c"}'),
        StepToolCall(id="d", name="stale_d", arguments='{"slot":"d"}'),
    ]

    results = await hub.dispatch(calls, _state())

    assert [item.tool_name for item in results] == [
        "live_a",
        "stale_b",
        "manage_watchlist",
        "live_c",
        "stale_d",
    ]
    assert [item.output for item in results] == [
        {"value": "live-a"},
        {"value": "stale-b"},
        {"created": False},
        {"value": "live-c"},
        {"value": "stale-d"},
    ]
    forwarded = inner.dispatch.await_args.args[0]
    assert [item.name for item in forwarded] == ["live_a", "manage_watchlist", "live_c"]
    inner.dispatch.assert_awaited_once()


def test_fault_target_that_is_not_a_registered_tool_fails_loudly() -> None:
    inner = Mock()
    inner.schemas_for_llm.return_value = [
        {"type": "function", "function": {"name": "get_market_quote"}}
    ]

    with pytest.raises(ValueError, match="unsupported fault target.*market_data"):
        FaultInjectingHub(inner, [FaultPlan(target="market_data", mode="stale")])


@pytest.mark.asyncio
async def test_watchlist_duplicate_add_conflict_passes_through_live_result_unchanged() -> None:
    inner = Mock()
    inner.schemas_for_llm.return_value = [
        {"type": "function", "function": {"name": "manage_watchlist"}}
    ]
    live_result = ToolResult(
        tool_name="manage_watchlist",
        args={"action": "add", "ts_code": "000063.SZ"},
        success=True,
        output={"created": False, "monitoring_enabled": True, "note": "5G设备"},
        error=None,
        latency_ms=7,
        tool_call_data={"source": "production"},
    )
    inner.dispatch = AsyncMock(return_value=[live_result])
    hub = FaultInjectingHub(
        inner,
        [
            FaultPlan(
                target="manage_watchlist",
                mode="conflict",
                payload={"kind": "duplicate_add", "same_payload": True},
            )
        ],
    )
    call = StepToolCall(
        id="watchlist-1",
        name="manage_watchlist",
        arguments='{"action":"add","ts_code":"000063.SZ"}',
    )
    state = _state()

    results = await hub.dispatch([call], state)

    assert results == [live_result]
    assert results[0] is live_result
    assert results[0].output == live_result.output
    assert results[0].error == live_result.error
    inner.dispatch.assert_awaited_once_with([call], state)


@pytest.mark.parametrize("mode", ["timeout", "error", "stale"])
@pytest.mark.asyncio
async def test_watchlist_duplicate_payload_only_passes_through_for_conflict(
    mode: FaultMode,
) -> None:
    inner = Mock()
    inner.schemas_for_llm.return_value = [
        {"type": "function", "function": {"name": "manage_watchlist"}}
    ]
    inner.dispatch = AsyncMock(
        return_value=[
            ToolResult(
                tool_name="manage_watchlist",
                args={"action": "add", "ts_code": "000063.SZ"},
                success=True,
                output={"source": "live"},
                latency_ms=1,
            )
        ]
    )
    payload = {"kind": "duplicate_add", "same_payload": True}
    hub = FaultInjectingHub(
        inner,
        [FaultPlan(target="manage_watchlist", mode=mode, payload=payload)],
    )
    call = StepToolCall(
        id="watchlist-1",
        name="manage_watchlist",
        arguments='{"action":"add","ts_code":"000063.SZ"}',
    )

    results = await hub.dispatch([call], _state())

    inner.dispatch.assert_not_awaited()
    if mode == "stale":
        assert results[0].success is True
        assert results[0].output == payload
        assert results[0].error is None
    else:
        assert results[0].success is False
        assert results[0].output is None
        assert results[0].error == f"[{mode}] eval-injected {mode}"


@pytest.mark.parametrize(
    ("target", "payload"),
    [
        ("manage_watchlist", {}),
        ("manage_watchlist", {"kind": "duplicate_add", "same_payload": False}),
        ("manage_watchlist", {"kind": "different_conflict", "same_payload": True}),
        (
            "manage_watchlist",
            {"kind": "duplicate_add", "same_payload": True, "unexpected": True},
        ),
        ("other_tool", {"kind": "duplicate_add", "same_payload": True}),
    ],
)
def test_generic_decorator_rejects_unknown_conflict_targets_and_payloads(
    target: str,
    payload: dict[str, object],
) -> None:
    inner = Mock()
    inner.schemas_for_llm.return_value = [
        {"type": "function", "function": {"name": name}}
        for name in ("manage_watchlist", "other_tool")
    ]

    with pytest.raises(ValueError, match="scenario-specific fault mode.*conflict"):
        FaultInjectingHub(
            inner,
            [FaultPlan(target=target, mode="conflict", payload=payload)],
        )


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
