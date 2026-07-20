from __future__ import annotations

from collections import UserDict
from unittest.mock import Mock

import pytest
from app.chatloop.continuation import ContinuationV1, PendingActionV1
from app.chatloop.gates import GateConfig, check_gates, filter_burned
from app.chatloop.state import ChatLoopState
from app.services.llm_step import StepToolCall
from pydantic import ValidationError


def _state() -> ChatLoopState:
    state = ChatLoopState(
        user_id="user-1",
        session_id="session-1",
        request_id="run-1",
        messages=[{"role": "user", "content": "需要我补充什么？"}],
    )
    state.step = 2
    state.ledger.record(
        step=1,
        tool_call_id="call-1",
        tool_name="search",
        args={"q": "贵州茅台"},
        digest="found",
        success=True,
    )
    return state


def test_continuation_round_trips_only_portable_whitelisted_state() -> None:
    state = _state()
    state.budget_spent_cny = 0.09
    state.budget_spent_tokens = 111
    state.prompt_tokens_total = 70
    state.completion_tokens_total = 41
    state.cached_tokens_total = 12
    state.burned_signatures = {state.ledger.entries[0].signature}
    continuation = ContinuationV1.from_state(
        state,
        PendingActionV1(
            pause_type="input",
            tool_name="ask_user",
            request={"question": "成本价是多少？"},
        ),
        key_id="key-1",
        signature="0" * 64,
        tenant_id="tenant-1",
    )

    payload = continuation.model_dump(mode="json")
    restored = ContinuationV1.model_validate(payload)

    assert restored.pending_action.tool_name == "ask_user"
    assert set(restored.body.model_dump()) == {
        "run_id",
        "session_id",
        "user_id",
        "tenant_id",
        "messages",
        "tool_ledger",
        "loop_count",
        "budget_spent_cny",
        "budget_spent_tokens",
        "prompt_tokens_total",
        "completion_tokens_total",
        "cached_tokens_total",
        "burned_signatures",
        "pending_action",
    }
    assert restored.body.tool_ledger[0].digest == "found"
    restored_state = restored.to_state()
    assert restored_state.budget_spent_cny == 0.09
    assert restored_state.budget_spent_tokens == 111
    assert restored_state.prompt_tokens_total == 70
    assert restored_state.completion_tokens_total == 41
    assert restored_state.cached_tokens_total == 12
    assert restored_state.burned_signatures == {state.ledger.entries[0].signature}
    assert check_gates(restored_state, GateConfig(max_cny=0.08)) == "budget"
    allowed, rejected = filter_burned(
        [
            StepToolCall(
                id="repeat",
                name="search",
                arguments='{"q":"\\u8d35\\u5dde\\u8305\\u53f0"}',
            )
        ],
        restored_state,
    )
    assert not allowed
    assert rejected == [state.ledger.entries[0].signature]


def test_continuation_accepts_large_legal_message_bounded_only_by_total_payload() -> None:
    state = _state()
    state.messages = [{"role": "user", "content": "x" * 33_000}]
    continuation = ContinuationV1.from_state(
        state,
        PendingActionV1(
            pause_type="input",
            tool_name="ask_user",
            request={"question": "cost?"},
        ),
        key_id="key-1",
        signature="0" * 64,
        tenant_id="tenant-1",
    )

    assert len(continuation.body.messages[0].content or "") == 33_000


def test_budget_accumulates_across_multiple_pause_snapshots() -> None:
    state = _state()
    state.budget_spent_cny = 0.04
    state.budget_spent_tokens = 40
    action = PendingActionV1(
        pause_type="input", tool_name="ask_user", request={"question": "first?"}
    )
    first = ContinuationV1.from_state(
        state, action, key_id="key-1", signature="0" * 64, tenant_id="tenant-1"
    ).to_state()
    first.budget_spent_cny += 0.07
    first.budget_spent_tokens += 70
    second = ContinuationV1.from_state(
        first, action, key_id="key-1", signature="0" * 64, tenant_id="tenant-1"
    ).to_state()

    assert second.budget_spent_cny == pytest.approx(0.11)
    assert second.budget_spent_tokens == 110
    assert check_gates(second, GateConfig(max_cny=0.10, max_tokens=1_000)) == "budget"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(version=2),
        lambda payload: payload.update(unexpected=True),
        lambda payload: payload["body"].update(runtime=Mock()),
        lambda payload: payload["body"]["messages"].append({"role": "user", "content": Mock()}),
        lambda payload: payload["body"]["messages"].append(
            {"role": "user", "content": "x" * (65 * 1024)}
        ),
    ],
)
def test_continuation_rejects_unknown_runtime_and_oversized_payload(mutation) -> None:
    payload = ContinuationV1.from_state(
        _state(),
        PendingActionV1(
            pause_type="input",
            tool_name="ask_user",
            request={"question": "成本价是多少？"},
        ),
        key_id="key-1",
        signature="0" * 64,
        tenant_id="tenant-1",
    ).model_dump(mode="json")
    mutation(payload)

    with pytest.raises((ValidationError, ValueError, TypeError)):
        ContinuationV1.model_validate(payload)


@pytest.mark.parametrize("version", [True, 1.0, "1"])
def test_continuation_version_is_strict_integer(version: object) -> None:
    payload = ContinuationV1.from_state(
        _state(),
        PendingActionV1(
            pause_type="input",
            tool_name="ask_user",
            request={"question": "cost?"},
        ),
        key_id="key-1",
        signature="0" * 64,
        tenant_id="tenant-1",
    ).model_dump(mode="json")
    payload["version"] = version

    with pytest.raises((ValidationError, ValueError, TypeError)):
        ContinuationV1.model_validate(payload)


@pytest.mark.parametrize(
    "runtime_value",
    [
        UserDict({"role": "user", "content": "forged"}),
        type("DictSubclass", (dict,), {})({"role": "user", "content": "forged"}),
        lambda: None,
    ],
)
def test_continuation_rejects_mapping_subclasses_and_callables(runtime_value: object) -> None:
    payload = ContinuationV1.from_state(
        _state(),
        PendingActionV1(
            pause_type="input",
            tool_name="ask_user",
            request={"question": "cost?"},
        ),
        key_id="key-1",
        signature="0" * 64,
        tenant_id="tenant-1",
    ).model_dump(mode="json")
    payload["body"]["messages"].append(runtime_value)

    with pytest.raises((ValidationError, ValueError, TypeError)):
        ContinuationV1.model_validate(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda body: body["messages"][0].update(extra="forbidden"),
        lambda body: body["tool_ledger"][0].update(step=True),
        lambda body: body["pending_action"].update(tool_name="x" * 257),
        lambda body: body["pending_action"]["request"].update(question="x" * 4097),
    ],
)
def test_continuation_nested_schema_is_strict_and_bounded(mutation) -> None:
    payload = ContinuationV1.from_state(
        _state(),
        PendingActionV1(
            pause_type="input",
            tool_name="ask_user",
            request={"question": "cost?"},
        ),
        key_id="key-1",
        signature="0" * 64,
        tenant_id="tenant-1",
    ).model_dump(mode="json")
    mutation(payload["body"])

    with pytest.raises((ValidationError, ValueError, TypeError)):
        ContinuationV1.model_validate(payload)
