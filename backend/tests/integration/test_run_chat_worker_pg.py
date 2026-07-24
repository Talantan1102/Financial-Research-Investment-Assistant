from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
import pytest_asyncio
from app.chatloop.gates import GateConfig
from app.chatloop.run_executor import CompletedResult, FailedResult, PauseResult, RunUsage
from app.chatloop.tool_hub import ToolHub
from app.models.run import Run, RunAttempt, RunEvent, RunMessage, RunPause, RunSession
from app.models.run_execution import RunToolExecution, RunUsageRecord
from app.models.run_scheduling import RunOutbox, RunWorker
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.services.attempt_service import AttemptCommandRejected, AttemptService
from app.services.llm_step import StepResult, StepToolCall
from app.services.run_chat_worker import (
    ContinuationKeyring,
    RunChatWorker,
    ToolRiskPolicy,
    build_chat_executor_builder,
)
from app.services.trace_models import TraceSpanRow
from app.tools.base import Tool
from eval.chatloop.scorers import PaperTradingOutcomeScorer
from eval.chatloop.sut_runner import DurableRunHttpTransport
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture
async def claimed(
    pg_async_session_factory: async_sessionmaker[AsyncSession],
    pg_test_engine: Any,
) -> tuple[AttemptService, Any, UUID]:
    del pg_test_engine
    async_session_factory = pg_async_session_factory
    suffix = uuid.uuid4().hex
    async with async_session_factory() as session, session.begin():
        user = User(
            username=f"run-chat-{suffix}",
            email=f"run-chat-{suffix}@example.com",
            hashed_password="hash",
        )
        tenant = Tenant(name=f"Run chat {suffix}", slug=f"run-chat-{suffix}")
        session.add_all([user, tenant])
        await session.flush()
        session.add(TenantMembership(tenant_id=tenant.id, user_id=user.id, role="member"))
        chat_session = RunSession(tenant_id=tenant.id, created_by_user_id=user.id)
        worker = RunWorker(
            worker_type="chat",
            capacity=1,
            status="online",
            heartbeat_at=func.timezone("UTC", func.statement_timestamp()),
            started_at=func.timezone("UTC", func.statement_timestamp()),
            metadata_payload={},
        )
        session.add_all([chat_session, worker])
        await session.flush()
        input_message = RunMessage(
            tenant_id=tenant.id,
            session_id=chat_session.id,
            role="user",
            content="question",
            status="complete",
        )
        session.add(input_message)
        await session.flush()
        run = Run(
            tenant_id=tenant.id,
            session_id=chat_session.id,
            created_by_user_id=user.id,
            run_type="chat",
            status="assigned",
            idempotency_key=f"run-chat-{suffix}",
            request_hash=uuid.uuid4().hex,
            input_message_id=input_message.id,
            revision_seq=1,
            retry_count=0,
        )
        session.add(run)
        await session.flush()
        attempt = RunAttempt(
            run_id=run.id,
            attempt_no=1,
            status="assigned",
            worker_id=worker.id,
            lease_expires_at=func.timezone("UTC", func.statement_timestamp())
            + timedelta(seconds=30),
        )
        session.add(attempt)
        await session.flush()
        session.add_all(
            [
                RunEvent(
                    tenant_id=tenant.id,
                    run_id=run.id,
                    seq=1,
                    event_type="run.created",
                    payload={"status": "queued"},
                ),
                RunEvent(
                    tenant_id=tenant.id,
                    run_id=run.id,
                    attempt_id=attempt.id,
                    seq=2,
                    event_type="run.assigned",
                    payload={"status": "assigned"},
                ),
                RunOutbox(
                    event_type="attempt.assigned",
                    tenant_id=tenant.id,
                    run_id=run.id,
                    attempt_id=attempt.id,
                    worker_id=worker.id,
                    payload={},
                    dedupe_key=f"attempt-assigned:{attempt.id}",
                ),
            ]
        )
        user_id = cast(uuid.UUID, user.id)
        attempt_id = cast(uuid.UUID, attempt.id)
        worker_id = cast(uuid.UUID, worker.id)
    service = AttemptService(async_session_factory, lease_duration=timedelta(seconds=30))
    claim = await service.claim(attempt_id, worker_id)
    assert claim.claimed and claim.assignment is not None
    return service, claim.assignment, user_id


def _usage() -> RunUsage:
    return RunUsage("test", "scripted", 3, 2, 1, 5, 0.125)


class _ReadArgs(BaseModel):
    query: str


class _ReadTool(Tool):
    name = "memory_search"
    description = "read"
    args_schema = _ReadArgs

    async def run(self, args: _ReadArgs) -> dict[str, Any]:
        return {"answer": args.query}


class _OrderArgs(BaseModel):
    symbol: str
    quantity: int


class _OrderTool(Tool):
    name = "place_order"
    description = "mutate"
    args_schema = _OrderArgs

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def run(self, args: _OrderArgs) -> dict[str, Any]:
        self.calls.append(args.symbol)
        return {"accepted": True}


class _ScriptedSteps:
    provider = "scripted"
    default_model = "scripted-v1"

    def __init__(self) -> None:
        self.steps = [
            StepResult(
                content="",
                tool_calls=[
                    StepToolCall(
                        id="call-production",
                        name="memory_search",
                        arguments='{"query":"position"}',
                    )
                ],
                finish_reason="tool_calls",
                prompt_tokens=2,
                completion_tokens=1,
                cached_tokens=0,
                cost_cny=0.0,
            ),
            StepResult(
                content="done",
                tool_calls=[],
                finish_reason="stop",
                prompt_tokens=2,
                completion_tokens=1,
                cached_tokens=0,
                cost_cny=0.0,
            ),
        ]

    async def stream_step(self, **_kwargs: Any) -> StepResult:
        return self.steps.pop(0)


@pytest.mark.asyncio
async def test_production_builder_runs_real_toolhub_toolloop_and_pg_ledger(
    claimed: tuple[AttemptService, Any, UUID],
    pg_async_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, assignment, _user_id = claimed
    llm = _ScriptedSteps()

    def components(_singletons: Any, **_kwargs: Any) -> Any:
        hub = ToolHub()
        hub.register_inprocess([_ReadTool()])
        return type(
            "Components",
            (),
            {
                "llm": llm,
                "tool_hub": hub,
                "gate_cfg": GateConfig(),
                "skill_listing": "",
                "system_prompt": "assistant",
            },
        )()

    monkeypatch.setitem(
        sys.modules,
        "app.chatloop.worker_wiring",
        SimpleNamespace(build_turn_components=components),
    )
    builder = build_chat_executor_builder(
        object(),
        provider="scripted",
        model="scripted-v1",
        risk_policy=ToolRiskPolicy.from_trusted_names({"memory_search"}),
    )

    await RunChatWorker(
        attempts=service,
        executor_builder=builder,
        continuation_keys=ContinuationKeyring(active_key_id="active", keys={"active": b"k" * 32}),
    ).execute_assignment(assignment)

    async with pg_async_session_factory() as session:
        run = await session.get(Run, assignment.run_id)
        row = await session.scalar(
            select(RunToolExecution).where(RunToolExecution.run_id == assignment.run_id)
        )
    assert run.status == "completed"
    assert row.status == "completed" and row.tool_call_id == "call-production"
    assert row.execution_epoch == 1 and row.reservation_token is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "decisions",
    [
        {"call-a": True, "call-b": False},
        {"call-a": True, "call-b": True},
        {"call-a": False, "call-b": False},
    ],
)
@pytest.mark.skip(
    reason="legacy batch-recovery fixture is superseded by the Compose recovery scenario"
)
async def test_recovery_batch_drains_all_decisions_before_one_builder_call(
    claimed: tuple[AttemptService, Any, UUID],
    pg_async_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    decisions: dict[str, bool],
) -> None:
    service, assignment, _user_id = claimed
    requests = {
        "call-a": {"symbol": "600519.SH", "quantity": 1},
        "call-b": {"symbol": "000001.SZ", "quantity": 2},
    }
    async with pg_async_session_factory() as session, session.begin():
        current = await session.get(RunAttempt, assignment.attempt_id)
        current.attempt_no = 2
        prior = RunAttempt(run_id=assignment.run_id, attempt_no=1, status="lost")
        session.add(prior)
        await session.flush()
        rows = []
        for index, (call_id, request) in enumerate(requests.items()):
            row = RunToolExecution(
                run_id=assignment.run_id,
                attempt_id=prior.id,
                tool_call_id=call_id,
                idempotency_key=service.tool_idempotency_key(
                    assignment.run_id, call_id, "place_order", request
                ),
                semantic_key=service.tool_semantic_key("place_order", request),
                tool_name="place_order",
                request_summary={"args": request},
                safe_to_retry=False,
                status="started" if index == 0 else "approval_required",
                reservation_token=uuid.uuid4() if index == 0 else None,
                reservation_expires_at=(
                    func.timezone("UTC", func.statement_timestamp()) + timedelta(seconds=30)
                    if index == 0
                    else None
                ),
                execution_epoch=1 if index == 0 else 0,
            )
            session.add(row)
            rows.append(row)
        await session.flush()
        execution_ids = {row.tool_call_id: row.id for row in rows}

    await RunChatWorker(
        attempts=service,
        executor_builder=lambda *_args: (_ for _ in ()).throw(
            AssertionError("builder before approval")
        ),
        continuation_keys=ContinuationKeyring(active_key_id="active", keys={"active": b"k" * 32}),
    ).execute_assignment(assignment)

    async with pg_async_session_factory() as session, session.begin():
        run = await session.get(Run, assignment.run_id)
        pause = await session.scalar(select(RunPause).where(RunPause.run_id == run.id))
        bindings = pause.request_payload["execution_bindings"]
        assert [binding["tool_call"]["id"] for binding in bindings] == ["call-a", "call-b"]
        assert {binding["execution_id"] for binding in bindings} == {
            str(value) for value in execution_ids.values()
        }
        pause.response_payload = {"decisions": decisions}
        pause.resolved_at = func.timezone("UTC", func.statement_timestamp())
        run.status = "assigned"
        run.queue_reason = "resume"
        next_attempt = RunAttempt(
            run_id=run.id,
            attempt_no=3,
            status="assigned",
            worker_id=assignment.worker_id,
            lease_expires_at=func.timezone("UTC", func.statement_timestamp())
            + timedelta(seconds=30),
        )
        session.add(next_attempt)
        await session.flush()
        next_attempt_id = next_attempt.id
    claim = await service.claim(next_attempt_id, assignment.worker_id)
    assert claim.claimed and claim.assignment is not None

    calls: list[str] = []
    builds = 0
    llm = _ScriptedSteps()

    def components(_singletons: Any, **_kwargs: Any) -> Any:
        nonlocal builds
        builds += 1
        hub = ToolHub()
        hub.register_inprocess([_OrderTool(calls)])
        return SimpleNamespace(
            llm=llm,
            tool_hub=hub,
            gate_cfg=GateConfig(),
            skill_listing="",
            system_prompt="assistant",
        )

    monkeypatch.setitem(
        sys.modules,
        "app.chatloop.worker_wiring",
        SimpleNamespace(build_turn_components=components),
    )
    builder = build_chat_executor_builder(
        object(),
        provider="scripted",
        model="scripted-v1",
        risk_policy=ToolRiskPolicy.from_trusted_names(set()),
    )
    await RunChatWorker(
        attempts=service,
        executor_builder=builder,
        continuation_keys=ContinuationKeyring(active_key_id="active", keys={"active": b"k" * 32}),
    ).execute_assignment(claim.assignment)

    async with pg_async_session_factory() as session:
        run = await session.get(Run, assignment.run_id)
        rows = {
            row.tool_call_id: row
            for row in (
                await session.scalars(
                    select(RunToolExecution).where(RunToolExecution.run_id == assignment.run_id)
                )
            ).all()
        }
    assert run.status == "completed"
    assert builds == 1
    assert calls == [requests[call_id]["symbol"] for call_id in requests if decisions[call_id]]
    assert all(
        rows[call_id].status == ("completed" if approved else "failed")
        and rows[call_id].error_code == (None if approved else "manual_rejected")
        for call_id, approved in decisions.items()
    )
    assert not any(row.status in {"started", "approval_required"} for row in rows.values())


@pytest.mark.asyncio
async def test_new_unsafe_row_forces_second_pause_and_rollback_keeps_builder_zero(
    claimed: tuple[AttemptService, Any, UUID],
    pg_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service, assignment, _user_id = claimed
    async with pg_async_session_factory() as session, session.begin():
        current = await session.get(RunAttempt, assignment.attempt_id)
        current.attempt_no = 2
        prior = RunAttempt(run_id=assignment.run_id, attempt_no=1, status="lost")
        session.add(prior)
        await session.flush()
        first_request = {"symbol": "600519.SH", "quantity": 1}
        first = RunToolExecution(
            run_id=assignment.run_id,
            attempt_id=prior.id,
            tool_call_id="call-first",
            idempotency_key=service.tool_idempotency_key(
                assignment.run_id, "call-first", "place_order", first_request
            ),
            semantic_key=service.tool_semantic_key("place_order", first_request),
            tool_name="place_order",
            request_summary={"args": first_request},
            safe_to_retry=False,
            status="approval_required",
            execution_epoch=0,
        )
        session.add(first)
        await session.flush()
        prior_id = prior.id

    builds = 0

    def forbidden_builder(*_args: Any) -> Any:
        nonlocal builds
        builds += 1
        raise AssertionError("builder must wait for every unsafe decision")

    keys = ContinuationKeyring(active_key_id="active", keys={"active": b"k" * 32})
    await RunChatWorker(
        attempts=service, executor_builder=forbidden_builder, continuation_keys=keys
    ).execute_assignment(assignment)

    async with pg_async_session_factory() as session, session.begin():
        run = await session.get(Run, assignment.run_id)
        pause = await session.scalar(select(RunPause).where(RunPause.run_id == run.id))
        pause.response_payload = {"approved": True}
        pause.resolved_at = func.timezone("UTC", func.statement_timestamp())
        second_request = {"symbol": "000001.SZ", "quantity": 2}
        session.add(
            RunToolExecution(
                run_id=assignment.run_id,
                attempt_id=prior_id,
                tool_call_id="call-second",
                idempotency_key=service.tool_idempotency_key(
                    assignment.run_id, "call-second", "place_order", second_request
                ),
                semantic_key=service.tool_semantic_key("place_order", second_request),
                tool_name="place_order",
                request_summary={"args": second_request},
                safe_to_retry=False,
                status="approval_required",
                execution_epoch=0,
            )
        )
        run.status = "assigned"
        run.queue_reason = "resume"
        next_attempt = RunAttempt(
            run_id=run.id,
            attempt_no=3,
            status="assigned",
            worker_id=assignment.worker_id,
            lease_expires_at=func.timezone("UTC", func.statement_timestamp())
            + timedelta(seconds=30),
        )
        session.add(next_attempt)
        await session.flush()
        next_attempt_id = next_attempt.id
    claim = await service.claim(next_attempt_id, assignment.worker_id)
    assert claim.claimed and claim.assignment is not None

    async def fail_second_pause() -> None:
        raise RuntimeError("second pause commit failure")

    service._before_chat_terminal_commit = fail_second_pause  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="second pause commit failure"):
        await RunChatWorker(
            attempts=service, executor_builder=forbidden_builder, continuation_keys=keys
        ).execute_assignment(claim.assignment)

    async with pg_async_session_factory() as session:
        run = await session.get(Run, assignment.run_id)
        pauses = tuple(
            (
                await session.scalars(
                    select(RunPause)
                    .where(RunPause.run_id == assignment.run_id)
                    .order_by(RunPause.pause_no)
                )
            ).all()
        )
    assert run.status == "running"
    assert len(pauses) == 1
    assert builds == 0

    async def allow_second_pause() -> None:
        return None

    service._before_chat_terminal_commit = allow_second_pause  # type: ignore[method-assign]
    await RunChatWorker(
        attempts=service, executor_builder=forbidden_builder, continuation_keys=keys
    ).execute_assignment(claim.assignment)
    async with pg_async_session_factory() as session:
        run = await session.get(Run, assignment.run_id)
        pauses = tuple(
            (
                await session.scalars(
                    select(RunPause)
                    .where(RunPause.run_id == assignment.run_id)
                    .order_by(RunPause.pause_no)
                )
            ).all()
        )
    assert run.status == "waiting_approval"
    assert len(pauses) == 2
    assert [
        binding["tool_call"]["id"] for binding in pauses[-1].request_payload["execution_bindings"]
    ] == ["call-first", "call-second"]
    assert builds == 0


@pytest.mark.asyncio
async def test_completed_result_commits_all_facts_atomically(
    claimed: tuple[AttemptService, Any, UUID],
    pg_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async_session_factory = pg_async_session_factory
    service, assignment, _user_id = claimed
    loaded = await service.load_chat_execution(assignment)
    result = CompletedResult(
        assignment.run_id,
        assignment.attempt_id,
        loaded.session_id,
        "durable answer",
        _usage(),
        (),
        (),
    )

    await service.complete_chat(assignment, result)

    async with async_session_factory() as session:
        run = await session.get(Run, assignment.run_id)
        attempt = await session.get(RunAttempt, assignment.attempt_id)
        message = await session.get(RunMessage, run.final_message_id)
        usage = await session.scalar(
            select(RunUsageRecord).where(RunUsageRecord.run_id == assignment.run_id)
        )
        trace = await session.scalar(
            select(TraceSpanRow).where(TraceSpanRow.request_id == str(assignment.run_id))
        )
        events = tuple(
            (
                await session.scalars(
                    select(RunEvent)
                    .where(RunEvent.run_id == assignment.run_id)
                    .order_by(RunEvent.seq)
                )
            ).all()
        )
    assert run.status == "completed" and run.final_message_id == message.id
    assert attempt.status == "completed" and attempt.claim_token is None
    assert (message.role, message.content, message.status) == (
        "assistant",
        "durable answer",
        "complete",
    )
    assert (usage.input_tokens, usage.output_tokens, usage.cached_tokens, usage.total_tokens) == (
        3,
        2,
        1,
        5,
    )
    assert usage.cost_cny == Decimal("0.12500000")
    assert trace.attrs_json["attempt_id"] == str(assignment.attempt_id)
    assert [event.event_type for event in events][-1] == "run.completed"


@pytest.mark.asyncio
async def test_injected_precommit_failure_rolls_back_every_completed_fact(
    claimed: tuple[AttemptService, Any, UUID],
    pg_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async_session_factory = pg_async_session_factory
    service, assignment, _user_id = claimed
    loaded = await service.load_chat_execution(assignment)
    result = CompletedResult(
        assignment.run_id,
        assignment.attempt_id,
        loaded.session_id,
        "must roll back",
        _usage(),
        (),
        (),
    )

    async def fail_before_commit() -> None:
        raise RuntimeError("injected before commit")

    service._before_chat_terminal_commit = fail_before_commit  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="injected before commit"):
        await service.complete_chat(assignment, result)

    async with async_session_factory() as session:
        run = await session.get(Run, assignment.run_id)
        attempt = await session.get(RunAttempt, assignment.attempt_id)
        assistant_count = await session.scalar(
            select(func.count())
            .select_from(RunMessage)
            .where(RunMessage.session_id == run.session_id, RunMessage.role == "assistant")
        )
        usage_count = await session.scalar(
            select(func.count())
            .select_from(RunUsageRecord)
            .where(RunUsageRecord.run_id == assignment.run_id)
        )
        trace_count = await session.scalar(
            select(func.count())
            .select_from(TraceSpanRow)
            .where(TraceSpanRow.request_id == str(assignment.run_id))
        )
    assert run.status == "running" and run.final_message_id is None
    assert attempt.status == "running" and attempt.claim_token == assignment.claim_token
    assert (assistant_count, usage_count, trace_count) == (0, 0, 0)


@pytest.mark.asyncio
async def test_pause_is_atomic_and_resolved_server_record_is_only_resume_source(
    claimed: tuple[AttemptService, Any, UUID],
    pg_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async_session_factory = pg_async_session_factory
    service, assignment, _user_id = claimed
    loaded = await service.load_chat_execution(assignment)
    paused = PauseResult(
        assignment.run_id,
        assignment.attempt_id,
        loaded.session_id,
        "approval",
        {"tool": "place_order"},
        {"version": 1, "key_id": "trusted", "body": {}, "signature": "sig"},
        _usage(),
        (),
        (),
    )
    await service.pause_chat(assignment, paused)
    async with async_session_factory() as session, session.begin():
        pause = await session.scalar(select(RunPause).where(RunPause.run_id == assignment.run_id))
        paused_event = await session.scalar(
            select(RunEvent).where(
                RunEvent.run_id == assignment.run_id,
                RunEvent.event_type == "run.paused",
            )
        )
        run = await session.get(Run, assignment.run_id)
        assert run.status == "waiting_approval"
        assert pause.resolved_at is None
        assert paused_event.payload["pause_type"] == "approval"
        assert paused_event.payload["request"] == {"tool": "place_order"}
        pause.response_payload = {
            "approved": True,
            "text": "continue",
            "edited_arguments": {"trade-1": {"quantity": 200}},
        }
        pause.resolved_at = func.timezone("UTC", func.statement_timestamp())
        run.status = "queued"
        run.queue_reason = "resume"

    # A later claimed Attempt loads only the persisted resolved pause.  No caller
    # parameter exists through which Redis/client continuation could replace it.
    async with async_session_factory() as session, session.begin():
        old_attempt = await session.get(RunAttempt, assignment.attempt_id)
        run = await session.get(Run, assignment.run_id)
        worker = await session.get(RunWorker, assignment.worker_id)
        new_attempt = RunAttempt(
            run_id=run.id,
            attempt_no=2,
            status="assigned",
            worker_id=worker.id,
            lease_expires_at=func.timezone("UTC", func.statement_timestamp())
            + timedelta(seconds=30),
        )
        session.add(new_attempt)
        await session.flush()
        run.status = "assigned"
        assert old_attempt.status == "paused"
        new_attempt_id = new_attempt.id
    second_claim = await service.claim(new_attempt_id, assignment.worker_id)
    assert second_claim.claimed and second_claim.assignment is not None
    resumed = await service.load_chat_execution(second_claim.assignment)
    assert resumed.continuation["key_id"] == "trusted"
    assert resumed.prompt == (
        '{"approved":true,"edited_arguments":{"trade-1":{"quantity":200}},"text":"continue"}'
    )


@pytest.mark.asyncio
async def test_injected_precommit_failure_rolls_back_pause_and_usage_trace(
    claimed: tuple[AttemptService, Any, UUID],
    pg_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service, assignment, _user_id = claimed
    loaded = await service.load_chat_execution(assignment)
    paused = PauseResult(
        assignment.run_id,
        assignment.attempt_id,
        loaded.session_id,
        "approval",
        {"reason": "manual"},
        {"version": 1, "key_id": "k", "body": {}, "signature": "s"},
        _usage(),
        (),
        (),
    )

    async def fail_before_commit() -> None:
        raise RuntimeError("injected pause commit failure")

    service._before_chat_terminal_commit = fail_before_commit  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="injected pause commit failure"):
        await service.pause_chat(assignment, paused)

    async with pg_async_session_factory() as session:
        run = await session.get(Run, assignment.run_id)
        attempt = await session.get(RunAttempt, assignment.attempt_id)
        pause_count = await session.scalar(
            select(func.count()).select_from(RunPause).where(RunPause.run_id == assignment.run_id)
        )
        usage_count = await session.scalar(
            select(func.count())
            .select_from(RunUsageRecord)
            .where(RunUsageRecord.run_id == assignment.run_id)
        )
    assert run.status == "running" and attempt.status == "running"
    assert pause_count == usage_count == 0


@pytest.mark.asyncio
async def test_zombie_token_cannot_write_terminal_or_tool_facts(
    claimed: tuple[AttemptService, Any, UUID],
    pg_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async_session_factory = pg_async_session_factory
    service, assignment, _user_id = claimed
    zombie = type(assignment)(
        tenant_id=assignment.tenant_id,
        run_id=assignment.run_id,
        attempt_id=assignment.attempt_id,
        worker_id=assignment.worker_id,
        claim_token=uuid.uuid4(),
        lease_expires_at=assignment.lease_expires_at,
    )
    loaded = await service.load_chat_execution(assignment)
    result = FailedResult(
        assignment.run_id,
        assignment.attempt_id,
        loaded.session_id,
        "executor_error",
        "safe",
        False,
        "",
        _usage(),
        (),
        (),
    )
    with pytest.raises(AttemptCommandRejected):
        await service.fail_chat(zombie, result)
    with pytest.raises(AttemptCommandRejected):
        await service.reserve_tool_execution(
            zombie,
            tool_call_id="call-1",
            tool_name="memory_write",
            request={"value": 1},
            safe_to_retry=False,
            approved=True,
        )

    async with async_session_factory() as session:
        facts = await session.scalar(
            select(func.count())
            .select_from(RunToolExecution)
            .where(RunToolExecution.run_id == assignment.run_id)
        )
        run = await session.get(Run, assignment.run_id)
    assert facts == 0 and run.status == "running"


@pytest.mark.asyncio
async def test_cancel_chat_persists_usage_trace_and_fenced_cancel_terminal(
    claimed: tuple[AttemptService, Any, UUID],
    pg_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service, assignment, _user_id = claimed
    loaded = await service.load_chat_execution(assignment)
    async with pg_async_session_factory() as session, session.begin():
        run = await session.get(Run, assignment.run_id)
        run.status = "cancel_requested"
        run.cancel_requested_at = func.timezone("UTC", func.statement_timestamp())
    result = FailedResult(
        assignment.run_id,
        assignment.attempt_id,
        loaded.session_id,
        "cancelled",
        "Run was cancelled.",
        False,
        "partial",
        _usage(),
        (),
        (),
    )

    await service.cancel_chat(assignment, result)

    async with pg_async_session_factory() as session:
        run = await session.get(Run, assignment.run_id)
        attempt = await session.get(RunAttempt, assignment.attempt_id)
        usage = await session.scalar(
            select(RunUsageRecord).where(RunUsageRecord.run_id == assignment.run_id)
        )
        trace = await session.scalar(
            select(TraceSpanRow).where(TraceSpanRow.request_id == str(assignment.run_id))
        )
    assert run.status == "cancelled" and attempt.status == "cancelled"
    assert usage.total_tokens == 5
    assert trace.attrs_json["status"] == "cancelled"


@pytest.mark.asyncio
async def test_server_history_limit_keeps_only_latest_messages_in_chronological_order(
    claimed: tuple[AttemptService, Any, UUID],
    pg_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _service, assignment, _user_id = claimed
    async with pg_async_session_factory() as session, session.begin():
        run = await session.get(Run, assignment.run_id)
        for content in ("history-1", "history-2", "history-3"):
            session.add(
                RunMessage(
                    tenant_id=run.tenant_id,
                    session_id=run.session_id,
                    role="assistant",
                    content=content,
                    status="complete",
                )
            )
            await session.flush()

    bounded = AttemptService(pg_async_session_factory, history_limit=2)
    loaded = await bounded.load_chat_execution(assignment)

    assert [message["content"] for message in loaded.history] == ["history-2", "history-3"]


@pytest.mark.asyncio
async def test_prior_attempt_unsafe_crash_creates_real_pause_before_builder(
    claimed: tuple[AttemptService, Any, UUID],
    pg_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service, assignment, _user_id = claimed
    semantic_key = service.tool_semantic_key("place_order", {"symbol": "600519.SH", "quantity": 1})
    async with pg_async_session_factory() as session, session.begin():
        current = await session.get(RunAttempt, assignment.attempt_id)
        current.attempt_no = 2
        prior = RunAttempt(
            run_id=assignment.run_id,
            attempt_no=1,
            status="lost",
            finished_at=func.timezone("UTC", func.statement_timestamp()),
        )
        session.add(prior)
        await session.flush()
        session.add(
            RunToolExecution(
                run_id=assignment.run_id,
                attempt_id=prior.id,
                tool_call_id="call-a",
                idempotency_key=service.tool_idempotency_key(
                    assignment.run_id,
                    "call-a",
                    "place_order",
                    {"symbol": "600519.SH", "quantity": 1},
                ),
                semantic_key=semantic_key,
                tool_name="place_order",
                request_summary={"args": {"symbol": "600519.SH", "quantity": 1}},
                safe_to_retry=False,
                status="started",
                reservation_token=uuid.uuid4(),
                reservation_expires_at=func.timezone("UTC", func.statement_timestamp())
                + timedelta(seconds=30),
                execution_epoch=1,
            )
        )

    builds = 0

    def forbidden_builder(*_args: Any) -> Any:
        nonlocal builds
        builds += 1
        raise AssertionError("builder must not run before unsafe recovery pause")

    await RunChatWorker(
        attempts=service,
        executor_builder=forbidden_builder,
        continuation_keys=ContinuationKeyring(active_key_id="active", keys={"active": b"k" * 32}),
    ).execute_assignment(assignment)

    async with pg_async_session_factory() as session:
        run = await session.get(Run, assignment.run_id)
        attempt = await session.get(RunAttempt, assignment.attempt_id)
        pause = await session.scalar(select(RunPause).where(RunPause.run_id == assignment.run_id))
    assert builds == 0
    assert run.status == "waiting_approval" and attempt.status == "paused"
    assert pause is not None and pause.pause_type == "approval"
    assert pause.request_payload["reason"] == "unsafe_tool_outcome_unknown"


@pytest.mark.asyncio
async def test_exact_execution_id_is_required_to_approve_existing_ledger_row(
    claimed: tuple[AttemptService, Any, UUID],
    pg_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service, assignment, _user_id = claimed
    request = {"symbol": "600519.SH", "quantity": 1}
    pending = await service.reserve_tool_execution(
        assignment,
        tool_call_id="call-exact",
        tool_name="place_order",
        request=request,
        safe_to_retry=False,
        approved=False,
        risk_level="high",
    )
    assert pending.status == "approval_required"
    async with pg_async_session_factory() as session:
        row = await session.scalar(
            select(RunToolExecution).where(
                RunToolExecution.run_id == assignment.run_id,
                RunToolExecution.tool_call_id == "call-exact",
            )
        )
        execution_id = row.id
        assert row.risk_level == "high"
        assert row.permission_decision == "approval_required"

    with pytest.raises(AttemptCommandRejected, match="approval provenance"):
        await service.reserve_tool_execution(
            assignment,
            tool_call_id="call-exact",
            tool_name="place_order",
            request=request,
            safe_to_retry=False,
            approved=True,
            risk_level="high",
            approved_execution_id=uuid.uuid4(),
        )
    approved = await service.reserve_tool_execution(
        assignment,
        tool_call_id="call-exact",
        tool_name="place_order",
        request=request,
        safe_to_retry=False,
        approved=True,
        risk_level="high",
        approved_execution_id=execution_id,
    )
    assert approved.execute and approved.execution_epoch == 1
    assert approved.reservation_token is not None
    async with pg_async_session_factory() as session:
        row = await session.get(RunToolExecution, execution_id)
    assert row.risk_level == "high"
    assert row.permission_decision == "approved"
    async with pg_async_session_factory() as session, session.begin():
        session.add(
            RunPause(
                run_id=assignment.run_id,
                pause_no=1,
                pause_type="approval",
                request_payload={
                    "tool_calls": [
                        {
                            "id": "call-exact",
                            "name": "place_order",
                            "arguments": request,
                            "risk_level": "high",
                            "permission_decision": "approval_required",
                        }
                    ]
                },
                continuation_payload={},
                response_payload={"approved": True},
                resolved_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
    transport = object.__new__(DurableRunHttpTransport)
    transport._session_factory = pg_async_session_factory
    calls, _run_state, _response = await transport._read_trace(str(assignment.run_id))
    assert calls[0]["permission_decisions"] == ["approval_required", "approved"]


@pytest.mark.asyncio
async def test_manual_reject_converges_exact_row_with_database_time(
    claimed: tuple[AttemptService, Any, UUID],
    pg_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service, assignment, _user_id = claimed
    await service.reserve_tool_execution(
        assignment,
        tool_call_id="call-reject",
        tool_name="memory_write",
        request={"memory": "x"},
        safe_to_retry=False,
        approved=False,
        risk_level="high",
    )
    async with pg_async_session_factory() as session:
        row = await session.scalar(
            select(RunToolExecution).where(
                RunToolExecution.run_id == assignment.run_id,
                RunToolExecution.tool_call_id == "call-reject",
            )
        )
        execution_id = row.id

    await service.reject_tool_execution(assignment, execution_id)

    async with pg_async_session_factory() as session:
        row = await session.get(RunToolExecution, execution_id)
    assert row.status == "failed" and row.error_code == "manual_rejected"
    assert row.risk_level == "high"
    assert row.permission_decision == "rejected"
    assert row.finished_at is not None
    assert row.reservation_token is None and row.reservation_expires_at is None
    async with pg_async_session_factory() as session, session.begin():
        session.add(
            RunPause(
                run_id=assignment.run_id,
                pause_no=1,
                pause_type="approval",
                request_payload={
                    "tool_calls": [
                        {
                            "id": "call-reject",
                            "name": "memory_write",
                            "arguments": {"memory": "x"},
                            "risk_level": "high",
                            "permission_decision": "approval_required",
                        }
                    ]
                },
                continuation_payload={},
                response_payload={"approved": False},
                resolved_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
    transport = object.__new__(DurableRunHttpTransport)
    transport._session_factory = pg_async_session_factory
    calls, _run_state, _response = await transport._read_trace(str(assignment.run_id))
    assert calls[0]["permission_decisions"] == ["approval_required", "rejected"]

    with pytest.raises(AttemptCommandRejected, match="rejection provenance"):
        await service.reject_tool_executions(assignment, (execution_id,))

    async with pg_async_session_factory() as session:
        row = await session.get(RunToolExecution, execution_id)
    assert row.status == "failed" and row.error_code == "manual_rejected"


@pytest.mark.asyncio
async def test_eval_trace_fails_when_persisted_permission_decision_is_unknown(
    claimed: tuple[AttemptService, Any, UUID],
    pg_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service, assignment, _user_id = claimed
    await service.reserve_tool_execution(
        assignment,
        tool_call_id="call-tampered-permission",
        tool_name="place_paper_order",
        request={"ts_code": "600519.SH", "side": "buy", "quantity": 100},
        safe_to_retry=False,
        approved=False,
        risk_level="high",
    )
    async with pg_async_session_factory() as session, session.begin():
        row = await session.scalar(
            select(RunToolExecution).where(
                RunToolExecution.run_id == assignment.run_id,
                RunToolExecution.tool_call_id == "call-tampered-permission",
            )
        )
        row.permission_decision = "unknown"
        session.add(
            RunPause(
                run_id=assignment.run_id,
                pause_no=1,
                pause_type="approval",
                request_payload={
                    "tool_calls": [
                        {
                            "id": "call-tampered-permission",
                            "name": "place_paper_order",
                            "arguments": {
                                "ts_code": "600519.SH",
                                "side": "buy",
                                "quantity": 100,
                            },
                            "risk_level": "high",
                            "permission_decision": "approval_required",
                        }
                    ]
                },
                continuation_payload={},
                response_payload={"approved": True},
                resolved_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )

    transport = object.__new__(DurableRunHttpTransport)
    transport._session_factory = pg_async_session_factory
    calls, _run_state, _response = await transport._read_trace(str(assignment.run_id))
    result = PaperTradingOutcomeScorer().score(
        {
            "version": 1,
            "type": "paper_trading",
            "expected_tools": ["place_paper_order"],
            "risk_levels": {"place_paper_order": "high"},
            "permission_decisions": {
                "place_paper_order": ["approval_required", "approved"],
            },
            "run": {
                "pause_type": "approval",
                "decision": "approved",
                "resumed": True,
                "status": "completed",
            },
            "database_assertions": {"snapshot_collected": True},
        },
        calls,
        {
            "observation": {"version": 1, "status": "collected"},
            "snapshot_collected": True,
        },
        {
            "observation": {"version": 1, "status": "collected"},
            **_run_state,
            "status": "completed",
        },
    )
    assert result.score == 0
    assert not result.passed
    assert "permission" in result.detail


@pytest.mark.asyncio
async def test_non_idempotent_unknown_is_not_reexecuted_after_crash(
    claimed: tuple[AttemptService, Any, UUID],
) -> None:
    service, assignment, _user_id = claimed
    first = await service.reserve_tool_execution(
        assignment,
        tool_call_id="call-side-effect",
        tool_name="memory_write",
        request={"memory": "x"},
        safe_to_retry=False,
        approved=True,
    )
    assert first.execute is True and first.status == "started"

    # Simulate process death after the side effect but before ledger completion.
    second = await service.reserve_tool_execution(
        assignment,
        tool_call_id="call-side-effect",
        tool_name="memory_write",
        request={"memory": "x"},
        safe_to_retry=False,
        approved=True,
    )
    assert second.execute is False
    assert second.status == "started"
    assert second.result is None


@pytest.mark.asyncio
async def test_two_sessions_issue_only_one_live_reservation_owner(
    claimed: tuple[AttemptService, Any, UUID],
) -> None:
    service, assignment, _user_id = claimed

    first, second = await asyncio.gather(
        service.reserve_tool_execution(
            assignment,
            tool_call_id="call-concurrent",
            tool_name="get_stock_quote",
            request={"ts_code": "600519.SH"},
            safe_to_retry=True,
            approved=False,
        ),
        service.reserve_tool_execution(
            assignment,
            tool_call_id="call-concurrent",
            tool_name="get_stock_quote",
            request={"ts_code": "600519.SH"},
            safe_to_retry=True,
            approved=False,
        ),
    )

    assert sum(item.execute for item in (first, second)) == 1
    owner = first if first.execute else second
    waiter = second if first.execute else first
    assert owner.reservation_token is not None and owner.execution_epoch == 1
    assert waiter.reservation_token is None and waiter.status == "started"


@pytest.mark.asyncio
async def test_expired_safe_reservation_can_be_stolen_but_old_owner_cannot_complete(
    claimed: tuple[AttemptService, Any, UUID],
    pg_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service, assignment, _user_id = claimed
    first = await service.reserve_tool_execution(
        assignment,
        tool_call_id="call-expiry",
        tool_name="get_stock_quote",
        request={"ts_code": "600519.SH"},
        safe_to_retry=True,
        approved=False,
    )
    async with pg_async_session_factory() as session, session.begin():
        row = await session.scalar(
            select(RunToolExecution).where(
                RunToolExecution.run_id == assignment.run_id,
                RunToolExecution.tool_call_id == "call-expiry",
            )
        )
        row.reservation_expires_at = func.timezone("UTC", func.statement_timestamp()) - timedelta(
            seconds=1
        )

    with pytest.raises(AttemptCommandRejected, match="reservation"):
        await service.complete_tool_execution(
            assignment,
            first.idempotency_key,
            {"success": True, "output": {}},
            reservation_token=first.reservation_token,
            execution_epoch=first.execution_epoch,
        )

    second = await service.reserve_tool_execution(
        assignment,
        tool_call_id="call-expiry",
        tool_name="get_stock_quote",
        request={"ts_code": "600519.SH"},
        safe_to_retry=True,
        approved=False,
    )

    assert second.execute and second.execution_epoch == 2
    assert second.reservation_token != first.reservation_token
    with pytest.raises(AttemptCommandRejected, match="reservation"):
        await service.complete_tool_execution(
            assignment,
            first.idempotency_key,
            {"success": True, "output": {}},
            reservation_token=first.reservation_token,
            execution_epoch=first.execution_epoch,
        )


@pytest.mark.asyncio
async def test_unsafe_same_semantics_with_new_call_id_requires_manual_approval(
    claimed: tuple[AttemptService, Any, UUID],
) -> None:
    service, assignment, _user_id = claimed
    first = await service.reserve_tool_execution(
        assignment,
        tool_call_id="call-a",
        tool_name="place_order",
        request={"symbol": "600519.SH", "quantity": 1},
        safe_to_retry=False,
        approved=True,
    )
    assert first.execute

    second = await service.reserve_tool_execution(
        assignment,
        tool_call_id="call-b",
        tool_name="place_order",
        request={"quantity": 1, "symbol": "600519.SH"},
        safe_to_retry=False,
        approved=False,
    )

    assert not second.execute and second.status == "approval_required"
    assert second.ambiguous is True


@pytest.mark.asyncio
async def test_non_idempotent_unknown_is_not_reexecuted_by_later_attempt_or_worker(
    claimed: tuple[AttemptService, Any, UUID],
    pg_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service, assignment, _user_id = claimed
    first = await service.reserve_tool_execution(
        assignment,
        tool_call_id="call-cross-attempt",
        tool_name="memory_write",
        request={"memory": "x"},
        safe_to_retry=False,
        approved=True,
    )
    assert first.execute is True

    async with pg_async_session_factory() as session, session.begin():
        old_attempt = await session.get(RunAttempt, assignment.attempt_id)
        run = await session.get(Run, assignment.run_id)
        replacement_worker = RunWorker(
            worker_type="chat",
            capacity=1,
            status="online",
            heartbeat_at=func.timezone("UTC", func.statement_timestamp()),
            started_at=func.timezone("UTC", func.statement_timestamp()),
            metadata_payload={},
        )
        session.add(replacement_worker)
        await session.flush()
        old_attempt.status = "lost"
        old_attempt.claim_token = None
        old_attempt.finished_at = func.timezone("UTC", func.statement_timestamp())
        new_attempt = RunAttempt(
            run_id=run.id,
            attempt_no=2,
            status="assigned",
            worker_id=replacement_worker.id,
            lease_expires_at=func.timezone("UTC", func.statement_timestamp())
            + timedelta(seconds=30),
        )
        session.add(new_attempt)
        await session.flush()
        run.status = "assigned"
        new_attempt_id = new_attempt.id
        replacement_worker_id = replacement_worker.id

    next_claim = await service.claim(new_attempt_id, replacement_worker_id)
    assert next_claim.claimed and next_claim.assignment is not None
    replay = await service.reserve_tool_execution(
        next_claim.assignment,
        tool_call_id="call-cross-attempt",
        tool_name="memory_write",
        request={"memory": "x"},
        safe_to_retry=False,
        approved=False,
    )
    assert replay.execute is False and replay.status == "started"


@pytest.mark.asyncio
async def test_completed_tool_result_is_reused_and_call_id_is_run_global(
    claimed: tuple[AttemptService, Any, UUID],
    pg_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service, assignment, _user_id = claimed
    reserved = await service.reserve_tool_execution(
        assignment,
        tool_call_id="call-read",
        tool_name="get_stock_quote",
        request={"ts_code": "600519.SH"},
        safe_to_retry=True,
        approved=False,
        risk_level="low",
    )
    assert reserved.execute is True
    cached_value = {"success": True, "output": {"price": 123}, "latency_ms": 4}
    await service.complete_tool_execution(
        assignment,
        reserved.idempotency_key,
        cached_value,
        reservation_token=reserved.reservation_token,
        execution_epoch=reserved.execution_epoch,
    )
    replay = await service.reserve_tool_execution(
        assignment,
        tool_call_id="call-read",
        tool_name="get_stock_quote",
        request={"ts_code": "600519.SH"},
        safe_to_retry=True,
        approved=False,
        risk_level="low",
    )
    assert replay.execute is False and replay.status == "completed"
    assert replay.result == cached_value
    async with pg_async_session_factory() as session:
        row = await session.scalar(
            select(RunToolExecution).where(
                RunToolExecution.run_id == assignment.run_id,
                RunToolExecution.tool_call_id == "call-read",
            )
        )
    assert row.risk_level == "low"
    assert row.permission_decision == "direct"
    transport = object.__new__(DurableRunHttpTransport)
    transport._session_factory = pg_async_session_factory
    calls, _run_state, _response = await transport._read_trace(str(assignment.run_id))
    assert calls[0]["permission_decisions"] == ["direct"]

    with pytest.raises(ValueError, match="tool_call_id"):
        await service.reserve_tool_execution(
            assignment,
            tool_call_id="call-read",
            tool_name="get_daily_basic",
            request={"ts_code": "600519.SH"},
            safe_to_retry=True,
            approved=False,
            risk_level="low",
        )


@pytest.mark.asyncio
async def test_failed_safe_tool_can_explicitly_retry(
    claimed: tuple[AttemptService, Any, UUID],
) -> None:
    service, assignment, _user_id = claimed
    first = await service.reserve_tool_execution(
        assignment,
        tool_call_id="call-safe-retry",
        tool_name="get_stock_quote",
        request={"ts_code": "600519.SH"},
        safe_to_retry=True,
        approved=False,
    )
    await service.fail_tool_execution(
        assignment,
        first.idempotency_key,
        error_code="upstream_timeout",
        error_message="safe failure",
        reservation_token=first.reservation_token,
        execution_epoch=first.execution_epoch,
    )

    retry = await service.reserve_tool_execution(
        assignment,
        tool_call_id="call-safe-retry",
        tool_name="get_stock_quote",
        request={"ts_code": "600519.SH"},
        safe_to_retry=True,
        approved=False,
    )
    assert retry.execute is True and retry.status == "started"


@pytest.mark.asyncio
async def test_invalid_usage_rolls_back_terminal_facts(
    claimed: tuple[AttemptService, Any, UUID],
    pg_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service, assignment, _user_id = claimed
    loaded = await service.load_chat_execution(assignment)
    invalid = CompletedResult(
        assignment.run_id,
        assignment.attempt_id,
        loaded.session_id,
        "must not persist",
        RunUsage("test", "scripted", 2, 2, 0, 5, 0.0),
        (),
        (),
    )
    with pytest.raises(ValueError, match="usage"):
        await service.complete_chat(assignment, invalid)

    async with pg_async_session_factory() as session:
        run = await session.get(Run, assignment.run_id)
        assistant_count = await session.scalar(
            select(func.count())
            .select_from(RunMessage)
            .where(RunMessage.session_id == run.session_id, RunMessage.role == "assistant")
        )
        usage_count = await session.scalar(
            select(func.count())
            .select_from(RunUsageRecord)
            .where(RunUsageRecord.run_id == assignment.run_id)
        )
    assert run.status == "running" and run.final_message_id is None
    assert assistant_count == usage_count == 0


@pytest.mark.asyncio
async def test_oversized_tool_json_is_rejected_without_false_completion(
    claimed: tuple[AttemptService, Any, UUID],
    pg_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service, assignment, _user_id = claimed
    with pytest.raises(ValueError, match="tool request exceeds"):
        await service.reserve_tool_execution(
            assignment,
            tool_call_id="call-oversized-request",
            tool_name="memory_write",
            request={"value": "中" * 6000},
            safe_to_retry=False,
            approved=True,
        )

    reserved = await service.reserve_tool_execution(
        assignment,
        tool_call_id="call-oversized-result",
        tool_name="memory_write",
        request={"value": "small"},
        safe_to_retry=False,
        approved=True,
    )
    with pytest.raises(ValueError, match="tool result exceeds"):
        await service.complete_tool_execution(
            assignment,
            reserved.idempotency_key,
            {"output": "中" * 22000},
        )

    async with pg_async_session_factory() as session:
        rows = tuple(
            (
                await session.scalars(
                    select(RunToolExecution).where(RunToolExecution.run_id == assignment.run_id)
                )
            ).all()
        )
    assert len(rows) == 1 and rows[0].status == "started"
