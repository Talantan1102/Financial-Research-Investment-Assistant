from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.chatloop.run_executor import CompletedResult, ExecuteChatRun, FailedResult, RunUsage
from app.services.attempt_service import ClaimedAssignment
from app.services.run_chat_worker import ContinuationKeyring, RunChatWorker


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
