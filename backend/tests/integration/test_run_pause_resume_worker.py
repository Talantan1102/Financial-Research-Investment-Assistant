from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from app.chatloop.continuation import ContinuationV1, PendingActionV1
from app.chatloop.contracts import ToolResult
from app.chatloop.control_tools import ApprovalTool
from app.chatloop.gates import GateConfig
from app.chatloop.run_executor import ChatRunExecutor, PauseResult, RunUsage
from app.chatloop.state import ChatLoopState
from app.models.run import Run, RunAttempt, RunPause
from app.models.run_scheduling import RunWorker
from app.services.attempt_service import AttemptService
from app.services.llm_step import StepResult, StepToolCall
from app.services.run_chat_worker import (
    ContinuationKeyring,
    DurableApprovalController,
    RunChatWorker,
    ToolRiskPolicy,
)
from app.services.run_service import RunService
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Reuse the real-PG assignment fixture that seeds a fully authoritative claimed
# Attempt.  Importing it here registers the fixture in this module as well.
from backend.tests.integration.test_run_chat_worker_pg import (  # noqa: F401
    claimed,
)


class _ScriptedLLM:
    provider = "test"
    default_model = "scripted"

    def __init__(self, steps: list[StepResult]) -> None:
        self.steps = list(steps)
        self.messages: list[list[dict[str, Any]]] = []

    async def stream_step(self, *, messages: list[dict[str, Any]], **_: Any) -> StepResult:
        self.messages.append(messages)
        return self.steps.pop(0)


class _ControlHub:
    def __init__(self) -> None:
        self.dispatched: list[str] = []

    def schemas_for_llm(self) -> list[dict[str, Any]]:
        return [ApprovalTool().schema_for_llm()]

    async def dispatch(self, calls: list[StepToolCall], state: ChatLoopState) -> list[ToolResult]:
        results: list[ToolResult] = []
        for call in calls:
            self.dispatched.append(call.id)
            args = call.parsed_args
            state.ledger.record(
                step=state.step,
                tool_call_id=call.id,
                tool_name=call.name,
                args=args,
                digest="approved",
                success=True,
            )
            results.append(
                ToolResult(
                    tool_name=call.name,
                    args=args,
                    success=True,
                    output={"approved": True},
                    latency_ms=0,
                )
            )
        return results


def _step(*, calls: list[StepToolCall] | None = None, text: str = "") -> StepResult:
    return StepResult(
        content=text,
        tool_calls=calls or [],
        finish_reason="tool_calls" if calls else "stop",
        prompt_tokens=1,
        completion_tokens=1,
        cached_tokens=0,
        cost_cny=0,
    )


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


async def _claim_on_new_worker(
    service: AttemptService,
    run_id: uuid.UUID,
    pg_async_session_factory: async_sessionmaker[AsyncSession],
) -> Any:
    async with pg_async_session_factory() as session, session.begin():
        run = await session.get(Run, run_id, with_for_update=True)
        second_worker = RunWorker(
            worker_type="chat",
            capacity=1,
            status="online",
            heartbeat_at=func.timezone("UTC", func.statement_timestamp()),
            started_at=func.timezone("UTC", func.statement_timestamp()),
            metadata_payload={},
        )
        session.add(second_worker)
        await session.flush()
        second_attempt = RunAttempt(
            run_id=run.id,
            attempt_no=2,
            status="assigned",
            worker_id=second_worker.id,
            lease_expires_at=func.timezone("UTC", func.statement_timestamp())
            + timedelta(seconds=30),
        )
        session.add(second_attempt)
        run.status = "assigned"
        await session.flush()
        attempt_id = cast(uuid.UUID, second_attempt.id)
        worker_id = cast(uuid.UUID, second_worker.id)
    claim = await service.claim(attempt_id, worker_id)
    assert claim.claimed and claim.assignment is not None
    return claim.assignment


@pytest.mark.parametrize(
    ("pause_type", "approved"),
    [("input", None), ("approval", True), ("approval", False)],
)
@pytest.mark.asyncio
async def test_run_worker_resumes_portable_pause_on_another_worker_and_finishes(
    claimed: tuple[AttemptService, Any, uuid.UUID],  # noqa: F811
    pg_async_session_factory: async_sessionmaker[AsyncSession],
    pause_type: str,
    approved: bool | None,
) -> None:
    service, first_assignment, user_id = claimed
    call = StepToolCall(
        id="control-1",
        name="ask_user" if pause_type == "input" else "approval",
        arguments=json.dumps({"question": "cost?" if pause_type == "input" else "proceed?"}),
    )
    first_llm = _ScriptedLLM([_step(calls=[call])])
    second_llm = _ScriptedLLM([_step(text="resumed answer")])
    first_hub = _ControlHub()
    second_hub = _ControlHub()
    policy = ToolRiskPolicy.from_trusted_names({"approval"})
    keyring = ContinuationKeyring(active_key_id="test", keys={"test": b"k" * 32})

    def builder(loaded, sink, cancel, _ledger, key):
        is_resume = loaded.continuation is not None
        return ChatRunExecutor(
            components=SimpleNamespace(
                llm=second_llm if is_resume else first_llm,
                tool_hub=second_hub if is_resume else first_hub,
                gate_cfg=GateConfig(),
                skill_listing="",
                system_prompt="test",
            ),
            event_sink=sink,
            cancel_event=cancel,
            user_id=loaded.user_id,
            continuation_secret=key.secret,
            continuation_key_id=key.key_id,
            pause_controller=DurableApprovalController(policy, frozenset()),
            provider="test",
            model="scripted",
        )

    first_worker = RunChatWorker(
        attempts=service,
        executor_builder=builder,
        continuation_keys=keyring,
        renew_interval=60,
    )
    await first_worker.execute_assignment(first_assignment)

    async with pg_async_session_factory() as session:
        paused_run = await session.get(Run, first_assignment.run_id)
        pause = await session.scalar(
            select(RunPause).where(RunPause.run_id == first_assignment.run_id)
        )
    assert pause is not None and pause.pause_type == pause_type, (
        paused_run.status,
        paused_run.error_code,
        paused_run.error_message,
    )
    assert paused_run.status == ("waiting_input" if pause_type == "input" else "waiting_approval")

    response = {"text": "1500"} if pause_type == "input" else {"approved": approved}
    await RunService(pg_async_session_factory).resume_run(
        first_assignment.tenant_id,
        first_assignment.run_id,
        user_id,
        response=response,
    )
    second_assignment = await _claim_on_new_worker(
        service, first_assignment.run_id, pg_async_session_factory
    )
    assert second_assignment.worker_id != first_assignment.worker_id
    second_worker = RunChatWorker(
        attempts=service,
        executor_builder=builder,
        continuation_keys=keyring,
        renew_interval=60,
    )
    await second_worker.execute_assignment(second_assignment)

    async with pg_async_session_factory() as session:
        run = await session.get(Run, first_assignment.run_id)
        attempts = (
            await session.scalars(
                select(RunAttempt)
                .where(RunAttempt.run_id == first_assignment.run_id)
                .order_by(RunAttempt.attempt_no)
            )
        ).all()
    assert run.status == "completed"
    assert run.retry_count == 0
    assert [attempt.status for attempt in attempts] == ["paused", "completed"]
    expected_resume = (
        "1500"
        if pause_type == "input"
        else json.dumps(response, ensure_ascii=False, sort_keys=True)
    )
    assert any(message.get("content") == expected_resume for message in second_llm.messages[0])
    assert second_hub.dispatched == (["control-1"] if approved is True else [])


@pytest.mark.asyncio
async def test_resolved_pause_resumes_on_a_different_worker_without_retry(
    claimed: tuple[AttemptService, Any, uuid.UUID],  # noqa: F811
    pg_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service, first_assignment, user_id = claimed
    loaded = await service.load_chat_execution(first_assignment)
    state = ChatLoopState(
        user_id=str(user_id),
        session_id=str(loaded.session_id),
        request_id=str(first_assignment.run_id),
        messages=[{"role": "user", "content": loaded.original_prompt}],
    )
    continuation = ContinuationV1.from_state(
        state,
        PendingActionV1(
            pause_type="input",
            tool_name="ask_user",
            request={"question": "成本价是多少？"},
        ),
        key_id="test",
        signature="0" * 64,
        tenant_id=str(first_assignment.tenant_id),
    ).model_dump(mode="json")
    await service.pause_chat(
        first_assignment,
        PauseResult(
            first_assignment.run_id,
            first_assignment.attempt_id,
            loaded.session_id,
            "input",
            {"question": "成本价是多少？"},
            continuation,
            RunUsage("test", "scripted", 0, 0, 0, 0, 0.0),
            (),
            (),
        ),
    )

    async with pg_async_session_factory() as session:
        run = await session.get(Run, first_assignment.run_id)
        tenant_id = cast(uuid.UUID, run.tenant_id)
    resumed = await RunService(pg_async_session_factory).resume_run(
        tenant_id,
        first_assignment.run_id,
        user_id,
        response={"text": "1500 元"},
    )
    assert resumed.retry_count == 0

    async with pg_async_session_factory() as session, session.begin():
        run = await session.get(Run, first_assignment.run_id, with_for_update=True)
        second_worker = RunWorker(
            worker_type="chat",
            capacity=1,
            status="online",
            heartbeat_at=func.timezone("UTC", func.statement_timestamp()),
            started_at=func.timezone("UTC", func.statement_timestamp()),
            metadata_payload={},
        )
        session.add(second_worker)
        await session.flush()
        second_attempt = RunAttempt(
            run_id=run.id,
            attempt_no=2,
            status="assigned",
            worker_id=second_worker.id,
            lease_expires_at=func.timezone("UTC", func.statement_timestamp())
            + timedelta(seconds=30),
        )
        session.add(second_attempt)
        run.status = "assigned"
        await session.flush()
        second_attempt_id = cast(uuid.UUID, second_attempt.id)
        second_worker_id = cast(uuid.UUID, second_worker.id)

    second_claim = await service.claim(second_attempt_id, second_worker_id)
    assert second_claim.claimed and second_claim.assignment is not None
    assert second_claim.assignment.worker_id != first_assignment.worker_id
    resumed_input = await service.load_chat_execution(second_claim.assignment)

    assert resumed_input.continuation == continuation
    assert resumed_input.prompt == '{"text":"1500 元"}'
    async with pg_async_session_factory() as session:
        run = await session.get(Run, first_assignment.run_id)
        pause = await session.scalar(
            select(RunPause).where(RunPause.run_id == first_assignment.run_id)
        )
    assert run.retry_count == 0
    assert pause is not None and pause.resolved_at is not None
