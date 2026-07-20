from __future__ import annotations

from collections import UserDict
from unittest.mock import Mock

import pytest
from app.chatloop.continuation import ContinuationV1, PendingActionV1
from app.chatloop.state import ChatLoopState
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
    continuation = ContinuationV1.from_state(
        _state(),
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
        "pending_action",
    }
    assert restored.body.tool_ledger[0].digest == "found"


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
