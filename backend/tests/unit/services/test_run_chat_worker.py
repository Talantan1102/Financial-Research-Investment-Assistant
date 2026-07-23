from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.chatloop.run_executor import CompletedResult, ExecuteChatRun, FailedResult, RunUsage
from app.chatloop.state import ChatLoopState
from app.services.attempt_service import AttemptCommandRejected, ClaimedAssignment
from app.services.llm_step import StepToolCall
from app.services.run_chat_worker import (
    ContinuationKeyring,
    DurableApprovalController,
    RunChatWorker,
    ToolRiskPolicy,
    load_continuation_keyring,
    load_tool_risk_policy,
    resolve_llm_identity,
)


@dataclass
class _BuiltExecutor:
    result: CompletedResult
    commands: list[ExecuteChatRun]
    closed: bool = False

    async def execute(self, command: ExecuteChatRun) -> CompletedResult:
        self.commands.append(command)
        return self.result

    async def aclose(self) -> None:
        self.closed = True


class _Attempts:
    def __init__(self, loaded: Any, result: CompletedResult) -> None:
        self.loaded = loaded
        self.result = result
        self.renewed = asyncio.Event()
        self.completed = 0
        self.failed = 0
        self.cancelled = 0
        self.paused = 0
        self.unsafe_recovery: dict[str, Any] | None = None

    async def load_chat_execution(self, assignment: ClaimedAssignment) -> Any:
        return self.loaded

    async def renew(self, attempt_id: UUID, worker_id: UUID, token: UUID) -> datetime:
        del attempt_id, worker_id, token
        self.renewed.set()
        return datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=30)

    async def complete_chat(self, assignment: ClaimedAssignment, result: CompletedResult) -> None:
        assert result is self.result
        self.completed += 1

    async def fail_chat(self, assignment: ClaimedAssignment, result: Any) -> None:
        del assignment, result
        self.failed += 1

    async def acknowledge_cancel(self, attempt_id: UUID, worker_id: UUID, token: UUID) -> None:
        del attempt_id, worker_id, token
        self.cancelled += 1

    async def cancel_chat(self, assignment: ClaimedAssignment, result: FailedResult) -> None:
        del assignment, result
        self.cancelled += 1

    async def pause_chat(self, assignment: ClaimedAssignment, result: Any) -> None:
        del assignment, result
        self.paused += 1

    async def find_unsafe_recovery(self, assignment: ClaimedAssignment) -> dict[str, Any] | None:
        del assignment
        return self.unsafe_recovery


@pytest.mark.asyncio
async def test_builder_failure_is_fenced_and_clears_cancel_registration() -> None:
    assignment = _assignment()
    session_id = uuid4()
    result = CompletedResult(
        assignment.run_id,
        assignment.attempt_id,
        session_id,
        "unused",
        RunUsage("test", "scripted", 0, 0, 0, 0, 0.0),
        (),
        (),
    )
    loaded = type(
        "Loaded",
        (),
        {
            "session_id": session_id,
            "user_id": uuid4(),
            "prompt": "question",
            "history": (),
            "continuation": None,
        },
    )()
    attempts = _Attempts(loaded, result)

    def broken_builder(*_args: Any) -> _BuiltExecutor:
        raise RuntimeError("builder exploded")

    worker = RunChatWorker(
        attempts=attempts,  # type: ignore[arg-type]
        executor_builder=broken_builder,
        continuation_keys=ContinuationKeyring(active_key_id="k1", keys={"k1": b"x" * 32}),
    )

    await worker.execute_assignment(assignment)

    assert attempts.failed == 1
    assert worker.request_cancel(assignment.attempt_id) is False


def _assignment() -> ClaimedAssignment:
    return ClaimedAssignment(
        tenant_id=uuid4(),
        run_id=uuid4(),
        attempt_id=uuid4(),
        worker_id=uuid4(),
        claim_token=uuid4(),
        lease_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=30),
    )


@pytest.mark.asyncio
async def test_server_risk_registry_fails_closed_except_explicit_safe_tools() -> None:
    policy = ToolRiskPolicy.from_trusted_names({"get_stock_quote"})
    state = ChatLoopState(user_id="u", session_id="s", request_id="r", messages=[])
    calls = (
        StepToolCall(id="order", name="place_order", arguments="{}"),
        StepToolCall(id="unknown", name="unknown_mcp", arguments="{}"),
        StepToolCall(id="read", name="get_stock_quote", arguments="{}"),
    )

    directive = await DurableApprovalController(policy, frozenset()).check(
        phase="before_tools", state=state, tool_calls=calls
    )

    assert directive is not None and directive.pause_type == "approval"
    assert [call["id"] for call in directive.request["tool_calls"]] == ["order", "unknown"]
    assert policy.safe_to_retry("place_order") is False
    assert policy.safe_to_retry("unknown_mcp") is False
    assert policy.safe_to_retry("get_stock_quote") is True
    production = load_tool_risk_policy({})
    for name in (
        "get_paper_account",
        "list_paper_orders",
        "get_paper_order",
        "manage_watchlist",
    ):
        assert production.safe_to_retry(name) is True
    for name in ("place_paper_order", "cancel_paper_order", "reset_paper_account"):
        assert production.safe_to_retry(name) is False


@pytest.mark.asyncio
async def test_only_paper_writes_are_declared_editable_before_dispatch() -> None:
    controller = DurableApprovalController(load_tool_risk_policy({}), frozenset())
    state = ChatLoopState(user_id="u", session_id="s", request_id="r", messages=[])
    directive = await controller.check(
        phase="before_tools",
        state=state,
        tool_calls=(
            StepToolCall(id="paper", name="place_paper_order", arguments="{}"),
            StepToolCall(id="other", name="memory_write", arguments="{}"),
        ),
    )
    assert directive is not None
    assert directive.request["editable_tool_call_ids"] == ["paper"]


@pytest.mark.asyncio
async def test_control_tools_map_to_typed_pauses_before_dispatch() -> None:
    controller = DurableApprovalController(ToolRiskPolicy.from_trusted_names(set()), frozenset())
    state = ChatLoopState(user_id="u", session_id="s", request_id="r", messages=[])

    asking = await controller.check(
        phase="before_tools",
        state=state,
        tool_calls=(StepToolCall(id="ask", name="ask_user", arguments='{"question":"cost?"}'),),
    )
    approving = await controller.check(
        phase="before_tools",
        state=state,
        tool_calls=(
            StepToolCall(id="approve", name="approval", arguments='{"question":"proceed?"}'),
        ),
    )

    assert asking is not None and asking.pause_type == "input"
    assert asking.request == {"tool_name": "ask_user", "question": "cost?"}
    assert approving is not None and approving.pause_type == "approval"
    assert approving.request["tool_calls"][0]["name"] == "approval"


@pytest.mark.asyncio
async def test_ask_user_must_be_the_only_tool_and_have_a_non_blank_question() -> None:
    controller = DurableApprovalController(ToolRiskPolicy.from_trusted_names(set()), frozenset())
    state = ChatLoopState(user_id="u", session_id="s", request_id="r", messages=[])
    with pytest.raises(ValueError, match="ask_user must be the only"):
        await controller.check(
            phase="before_tools",
            state=state,
            tool_calls=(
                StepToolCall(id="ask", name="ask_user", arguments='{"question":"cost?"}'),
                StepToolCall(id="write", name="memory_write", arguments="{}"),
            ),
        )
    with pytest.raises(ValueError, match="question"):
        await controller.check(
            phase="before_tools",
            state=state,
            tool_calls=(StepToolCall(id="ask", name="ask_user", arguments='{"question":" "}'),),
        )


def test_production_risk_catalog_defaults_to_real_reads_and_rejects_unknown_config() -> None:
    policy = load_tool_risk_policy({})
    assert policy.safe_to_retry("memory_search") is True
    assert policy.safe_to_retry("search_tools") is True
    assert policy.safe_to_retry("memory_write") is False
    assert policy.safe_to_retry("place_order") is False
    with pytest.raises(ValueError, match="untrusted safe tool names"):
        load_tool_risk_policy({"RUN_SAFE_IDEMPOTENT_TOOLS": "memory_search,place_order"})


def test_server_keyring_supports_rotation_and_legacy_fallback_without_client_material() -> None:
    rotated = load_continuation_keyring(
        {
            "RUN_CONTINUATION_HMAC_ACTIVE_KEY_ID": "new",
            "RUN_CONTINUATION_HMAC_KEYS_JSON": json.dumps({"old": "o" * 32, "new": "n" * 32}),
        }
    )
    assert rotated.active_key_id == "new"
    assert rotated.select({"key_id": "old"}).secret == b"o" * 32
    assert rotated.select(None).secret == b"n" * 32

    legacy = load_continuation_keyring(
        {
            "RUN_CONTINUATION_HMAC_KEY_ID": "legacy",
            "RUN_CONTINUATION_HMAC_SECRET": "s" * 32,
        }
    )
    assert legacy.active_key_id == "legacy"
    with pytest.raises(ValueError, match="configuration"):
        load_continuation_keyring(
            {
                "RUN_CONTINUATION_HMAC_ACTIVE_KEY_ID": "missing",
                "RUN_CONTINUATION_HMAC_KEYS_JSON": json.dumps({"other": "x" * 32}),
            }
        )


def test_usage_identity_is_resolved_from_the_actual_llm_instance() -> None:
    llm = type("ResolvedLLM", (), {"provider": "custom-provider", "default_model": "model-x"})()
    assert resolve_llm_identity(llm) == ("custom-provider", "model-x")


@pytest.mark.asyncio
async def test_execute_assignment_loads_server_context_renews_and_always_closes() -> None:
    assignment = _assignment()
    usage = RunUsage("test", "scripted", 2, 1, 0, 3, 0.0)
    result = CompletedResult(
        assignment.run_id,
        assignment.attempt_id,
        uuid4(),
        "answer",
        usage,
        (),
        (),
    )
    loaded = type(
        "Loaded",
        (),
        {
            "session_id": result.session_id,
            "user_id": uuid4(),
            "prompt": "question",
            "history": ({"role": "assistant", "content": "old"},),
            "continuation": None,
        },
    )()
    attempts = _Attempts(loaded, result)
    built = _BuiltExecutor(result, [])

    worker = RunChatWorker(
        attempts=attempts,  # type: ignore[arg-type]
        executor_builder=lambda _loaded, _sink, _cancel, _ledger, _key: built,
        continuation_keys=ContinuationKeyring(active_key_id="k1", keys={"k1": b"x" * 32}),
        renew_interval=0.001,
    )
    await worker.execute_assignment(assignment)

    assert attempts.completed == 1
    assert attempts.renewed.is_set()
    assert built.closed is True
    assert built.commands == [
        ExecuteChatRun(
            run_id=assignment.run_id,
            attempt_id=assignment.attempt_id,
            session_id=result.session_id,
            prompt="question",
            history=({"role": "assistant", "content": "old"},),
            continuation=None,
            tenant_id=assignment.tenant_id,
        )
    ]


@pytest.mark.asyncio
async def test_continuation_key_id_selects_only_trusted_server_key() -> None:
    assignment = _assignment()
    session_id = uuid4()
    keyring = ContinuationKeyring(
        active_key_id="new",
        keys={"old": b"o" * 32, "new": b"n" * 32},
    )
    loaded = type(
        "Loaded",
        (),
        {
            "session_id": session_id,
            "user_id": uuid4(),
            "prompt": json.dumps({"approved": True}),
            "history": (),
            "continuation": {"version": 1, "key_id": "old", "body": {}, "signature": "x"},
        },
    )()
    result = CompletedResult(
        assignment.run_id,
        assignment.attempt_id,
        session_id,
        "answer",
        RunUsage("test", "scripted", 0, 0, 0, 0, 0.0),
        (),
        (),
    )
    attempts = _Attempts(loaded, result)
    selected: list[tuple[str, bytes]] = []

    def build(_loaded: Any, _sink: Any, _cancel: Any, _ledger: Any, key: Any) -> _BuiltExecutor:
        selected.append((key.key_id, key.secret))
        return _BuiltExecutor(result, [])

    await RunChatWorker(
        attempts=attempts,  # type: ignore[arg-type]
        executor_builder=build,
        continuation_keys=keyring,
        renew_interval=0.001,
    ).execute_assignment(assignment)

    assert selected == [("old", b"o" * 32)]


@pytest.mark.asyncio
async def test_terminal_transaction_failure_is_not_reclassified_as_executor_failure() -> None:
    assignment = _assignment()
    session_id = uuid4()
    result = CompletedResult(
        assignment.run_id,
        assignment.attempt_id,
        session_id,
        "answer",
        RunUsage("test", "scripted", 0, 0, 0, 0, 0.0),
        (),
        (),
    )
    loaded = type(
        "Loaded",
        (),
        {
            "session_id": session_id,
            "user_id": uuid4(),
            "prompt": "question",
            "history": (),
            "continuation": None,
        },
    )()
    attempts = _Attempts(loaded, result)

    async def fail_commit(_assignment: ClaimedAssignment, _result: CompletedResult) -> None:
        raise RuntimeError("injected terminal commit failure")

    attempts.complete_chat = fail_commit  # type: ignore[method-assign]
    worker = RunChatWorker(
        attempts=attempts,  # type: ignore[arg-type]
        executor_builder=lambda _loaded, _sink, _cancel, _ledger, _key: _BuiltExecutor(result, []),
        continuation_keys=ContinuationKeyring(active_key_id="k1", keys={"k1": b"x" * 32}),
        renew_interval=0.001,
    )

    with pytest.raises(RuntimeError, match="injected terminal commit failure"):
        await worker.execute_assignment(assignment)
    assert attempts.failed == 0


@pytest.mark.asyncio
async def test_request_cancel_reaches_executor_event_and_uses_fenced_cancel_terminal() -> None:
    assignment = _assignment()
    session_id = uuid4()
    usage = RunUsage("test", "scripted", 0, 0, 0, 0, 0.0)
    loaded = type(
        "Loaded",
        (),
        {
            "session_id": session_id,
            "user_id": uuid4(),
            "prompt": "question",
            "history": (),
            "continuation": None,
        },
    )()
    placeholder = CompletedResult(
        assignment.run_id, assignment.attempt_id, session_id, "unused", usage, (), ()
    )
    attempts = _Attempts(loaded, placeholder)
    started = asyncio.Event()

    class CancelExecutor:
        def __init__(self, cancel: asyncio.Event) -> None:
            self.cancel = cancel

        async def execute(self, _command: ExecuteChatRun) -> FailedResult:
            started.set()
            await self.cancel.wait()
            return FailedResult(
                assignment.run_id,
                assignment.attempt_id,
                session_id,
                "cancelled",
                "Run was cancelled.",
                False,
                "",
                usage,
                (),
                (),
            )

    worker = RunChatWorker(
        attempts=attempts,  # type: ignore[arg-type]
        executor_builder=lambda _loaded, _sink, cancel, _ledger, _key: CancelExecutor(cancel),
        continuation_keys=ContinuationKeyring(active_key_id="k1", keys={"k1": b"x" * 32}),
        renew_interval=0.001,
    )
    execution = asyncio.create_task(worker.execute_assignment(assignment))
    await started.wait()
    assert worker.request_cancel(assignment.attempt_id) is True
    await execution

    assert attempts.cancelled == 1
    assert attempts.failed == 0


@pytest.mark.asyncio
async def test_renew_failure_cancels_executor_before_side_effect_and_does_not_write_terminal() -> (
    None
):
    assignment = _assignment()
    session_id = uuid4()
    usage = RunUsage("test", "scripted", 0, 0, 0, 0, 0.0)
    loaded = type(
        "Loaded",
        (),
        {
            "session_id": session_id,
            "user_id": uuid4(),
            "prompt": "question",
            "history": (),
            "continuation": None,
        },
    )()
    placeholder = CompletedResult(
        assignment.run_id, assignment.attempt_id, session_id, "unused", usage, (), ()
    )
    attempts = _Attempts(loaded, placeholder)

    async def reject_renew(*_args: Any) -> datetime:
        raise AttemptCommandRejected("lease lost")

    attempts.renew = reject_renew  # type: ignore[method-assign]
    side_effects = 0

    class WaitingExecutor:
        def __init__(self, cancel: asyncio.Event) -> None:
            self.cancel = cancel

        async def execute(self, _command: ExecuteChatRun) -> CompletedResult:
            nonlocal side_effects
            await asyncio.sleep(0.02)
            if not self.cancel.is_set():
                side_effects += 1
            await self.cancel.wait()
            return placeholder

    worker = RunChatWorker(
        attempts=attempts,  # type: ignore[arg-type]
        executor_builder=lambda _loaded, _sink, cancel, _ledger, _key: WaitingExecutor(cancel),
        continuation_keys=ContinuationKeyring(active_key_id="k1", keys={"k1": b"x" * 32}),
        renew_interval=0.001,
    )

    with pytest.raises(AttemptCommandRejected, match="lease lost"):
        await worker.execute_assignment(assignment)
    assert side_effects == 0
    assert attempts.completed == attempts.failed == attempts.cancelled == 0


@pytest.mark.asyncio
async def test_prior_unsafe_started_row_pauses_before_model_or_tool_builder() -> None:
    assignment = _assignment()
    session_id = uuid4()
    result = CompletedResult(
        assignment.run_id,
        assignment.attempt_id,
        session_id,
        "unused",
        RunUsage("test", "scripted", 0, 0, 0, 0, 0.0),
        (),
        (),
    )
    loaded = type(
        "Loaded",
        (),
        {
            "session_id": session_id,
            "user_id": uuid4(),
            "prompt": "question",
            "history": (),
            "continuation": None,
        },
    )()
    attempts = _Attempts(loaded, result)
    attempts.unsafe_recovery = {
        "execution_id": str(uuid4()),
        "tool_call_id": "call-a",
        "tool_name": "place_order",
        "request": {"symbol": "600519.SH", "quantity": 1},
        "semantic_key": "abc",
    }
    builds = 0

    def forbidden_builder(*_args: Any) -> _BuiltExecutor:
        nonlocal builds
        builds += 1
        return _BuiltExecutor(result, [])

    await RunChatWorker(
        attempts=attempts,  # type: ignore[arg-type]
        executor_builder=forbidden_builder,
        continuation_keys=ContinuationKeyring(active_key_id="k1", keys={"k1": b"x" * 32}),
    ).execute_assignment(assignment)

    assert builds == 0
    assert attempts.paused == 1
    assert attempts.renewed.is_set()
