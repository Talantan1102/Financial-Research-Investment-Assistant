from __future__ import annotations

import asyncio
import sys
import uuid

import pytest
import pytest_asyncio
from app.models.run import Run, RunEvent
from app.models.run_scheduling import RunOutbox
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.run_control.types import (
    InvalidRunTransition,
    ResourceNotFound,
    ResumeNotAllowed,
    RunStatus,
)
from app.services.run_service import CreateRunCommand, RunService
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.helpers.run_fake_executor import FakeRunExecutor


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture
async def lifecycle_context(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> tuple[Tenant, User, User]:
    suffix = uuid.uuid4().hex[:12]
    member = User(
        username=f"lifecycle-member-{suffix}",
        email=f"lifecycle-member-{suffix}@example.com",
        hashed_password="test-password-hash",
    )
    outsider = User(
        username=f"lifecycle-outsider-{suffix}",
        email=f"lifecycle-outsider-{suffix}@example.com",
        hashed_password="test-password-hash",
    )
    tenant = Tenant(name="Lifecycle tenant", slug=f"lifecycle-{suffix}")
    async with async_session_factory() as session, session.begin():
        session.add_all([member, outsider, tenant])
        await session.flush()
        session.add(TenantMembership(tenant_id=tenant.id, user_id=member.id, role="member"))
    return tenant, member, outsider


@pytest.fixture
def run_service(async_session_factory: async_sessionmaker[AsyncSession]) -> RunService:
    return RunService(async_session_factory)


@pytest_asyncio.fixture
async def created_run(
    run_service: RunService,
    lifecycle_context: tuple[Tenant, User, User],
) -> Run:
    tenant, member, _outsider = lifecycle_context
    created = await run_service.create_run(
        CreateRunCommand(
            tenant_id=tenant.id,
            actor_id=member.id,
            session_id=None,
            prompt="分析这笔持仓。",
            idempotency_key=f"lifecycle-{uuid.uuid4().hex}",
            replaces_run_id=None,
        )
    )
    return created.run


@pytest.fixture
def fake_executor(run_service: RunService, created_run: Run) -> FakeRunExecutor:
    return FakeRunExecutor(
        run_service,
        created_run.tenant_id,
        created_run.created_by_user_id,
    )


@pytest.mark.asyncio
async def test_cancel_queued_finishes_immediately(
    run_service: RunService,
    created_run: Run,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    result = await run_service.cancel_run(
        created_run.tenant_id, created_run.id, created_run.created_by_user_id
    )

    assert result.status == RunStatus.CANCELLED.value
    assert result.finished_at is not None
    assert result.cancel_requested_at is None
    events = await run_service.list_events(
        created_run.tenant_id, created_run.id, created_run.created_by_user_id
    )
    assert [(event.seq, event.event_type) for event in events] == [
        (1, "run.created"),
        (2, "run.cancelled"),
    ]
    async with async_session_factory() as session:
        cancel_count = await session.scalar(
            select(func.count())
            .select_from(RunOutbox)
            .where(
                RunOutbox.run_id == created_run.id,
                RunOutbox.event_type == "attempt.cancel",
            )
        )
    assert cancel_count == 0


@pytest.mark.asyncio
async def test_cancel_running_requests_cooperative_cancellation(
    run_service: RunService,
    fake_executor: FakeRunExecutor,
    created_run: Run,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await fake_executor.start(created_run.id)

    result = await run_service.cancel_run(
        created_run.tenant_id, created_run.id, created_run.created_by_user_id
    )

    assert result.status == RunStatus.CANCEL_REQUESTED.value
    assert result.cancel_requested_at is not None
    assert result.finished_at is None
    async with async_session_factory() as session:
        cancel_outbox = await session.scalar(
            select(RunOutbox).where(
                RunOutbox.run_id == created_run.id,
                RunOutbox.event_type == "attempt.cancel",
            )
        )
    assert cancel_outbox is not None
    assert cancel_outbox.payload == {"run_id": str(created_run.id)}
    assert cancel_outbox.dedupe_key == f"attempt.cancel:{created_run.id}"


@pytest.mark.asyncio
async def test_cancel_assigned_also_writes_cooperative_cancel_outbox(
    run_service: RunService,
    created_run: Run,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await run_service.transition_run(
        created_run.tenant_id,
        created_run.id,
        created_run.created_by_user_id,
        RunStatus.ASSIGNED,
        event_type="run.assigned",
    )

    result = await run_service.cancel_run(
        created_run.tenant_id, created_run.id, created_run.created_by_user_id
    )

    assert result.status == RunStatus.CANCEL_REQUESTED.value
    async with async_session_factory() as session:
        cancel_outbox = await session.scalar(
            select(RunOutbox).where(
                RunOutbox.run_id == created_run.id,
                RunOutbox.event_type == "attempt.cancel",
            )
        )
    assert cancel_outbox is not None
    assert cancel_outbox.dedupe_key == f"attempt.cancel:{created_run.id}"


@pytest.mark.asyncio
async def test_cancel_terminal_is_idempotent_without_new_event(
    run_service: RunService, created_run: Run
) -> None:
    first = await run_service.cancel_run(
        created_run.tenant_id, created_run.id, created_run.created_by_user_id
    )
    second = await run_service.cancel_run(
        created_run.tenant_id, created_run.id, created_run.created_by_user_id
    )

    assert second.status == first.status == RunStatus.CANCELLED.value
    events = await run_service.list_events(
        created_run.tenant_id, created_run.id, created_run.created_by_user_id
    )
    assert [event.event_type for event in events].count("run.cancelled") == 1


@pytest.mark.asyncio
async def test_resume_waiting_keeps_same_run_and_resolves_pause(
    run_service: RunService,
    fake_executor: FakeRunExecutor,
    created_run: Run,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await fake_executor.start(created_run.id)
    pause = await fake_executor.pause_for_input(
        created_run.id,
        {"question": "你的成本价是多少？"},
        {"checkpoint": "ask-cost"},
    )

    resumed = await run_service.resume_run(
        created_run.tenant_id,
        created_run.id,
        created_run.created_by_user_id,
        response={"text": "成本价 1500"},
    )

    resolved = await run_service.get_pause(
        created_run.tenant_id,
        created_run.id,
        created_run.created_by_user_id,
        pause.id,
    )
    assert resumed.id == created_run.id
    assert resumed.status == RunStatus.QUEUED.value
    assert resumed.queue_reason == "resume"
    assert resolved.response_payload == {"text": "成本价 1500"}
    assert resolved.resolved_at is not None
    async with async_session_factory() as session:
        wakes = tuple(
            (
                await session.scalars(
                    select(RunOutbox)
                    .where(
                        RunOutbox.run_id == created_run.id,
                        RunOutbox.event_type == "schedule.wake",
                    )
                    .order_by(RunOutbox.created_at)
                )
            ).all()
        )
    assert len(wakes) == 2
    assert wakes[-1].payload == {"run_id": str(created_run.id), "reason": "resume"}
    assert wakes[-1].dedupe_key == f"schedule.wake:{created_run.id}:resume:{pause.id}"


@pytest.mark.asyncio
async def test_resume_outbox_conflict_rolls_back_run_pause_event_and_outbox(
    run_service: RunService,
    fake_executor: FakeRunExecutor,
    created_run: Run,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await fake_executor.start(created_run.id)
    pause = await fake_executor.pause_for_input(created_run.id, {"question": "cost?"})
    dedupe_key = f"schedule.wake:{created_run.id}:resume:{pause.id}"
    async with async_session_factory() as session, session.begin():
        session.add(
            RunOutbox(
                event_type="schedule.wake",
                tenant_id=created_run.tenant_id,
                run_id=created_run.id,
                payload={"preexisting": True},
                dedupe_key=dedupe_key,
            )
        )

    with pytest.raises(IntegrityError):
        await run_service.resume_run(
            created_run.tenant_id,
            created_run.id,
            created_run.created_by_user_id,
            response={"text": "1500"},
        )

    current = await run_service.get_run(
        created_run.tenant_id, created_run.id, created_run.created_by_user_id
    )
    unresolved = await run_service.get_pause(
        created_run.tenant_id,
        created_run.id,
        created_run.created_by_user_id,
        pause.id,
    )
    events = await run_service.list_events(
        created_run.tenant_id, created_run.id, created_run.created_by_user_id
    )
    async with async_session_factory() as session:
        duplicate_count = await session.scalar(
            select(func.count()).select_from(RunOutbox).where(RunOutbox.dedupe_key == dedupe_key)
        )
    assert current.status == RunStatus.WAITING_INPUT.value
    assert unresolved.resolved_at is None
    assert unresolved.response_payload is None
    assert not any(event.event_type == "run.resumed" for event in events)
    assert duplicate_count == 1


@pytest.mark.asyncio
async def test_invalid_resume_is_rejected(run_service: RunService, created_run: Run) -> None:
    with pytest.raises(ResumeNotAllowed):
        await run_service.resume_run(
            created_run.tenant_id,
            created_run.id,
            created_run.created_by_user_id,
            response={"text": "没有 pause"},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pause_kind", "response"),
    [
        ("input", {"approved": True}),
        ("input", {"text": 123}),
        ("approval", {"text": "yes"}),
        ("approval", {"approved": "yes"}),
        ("approval", {"approved": True, "decisions": {"call-1": True}}),
    ],
)
async def test_resume_validates_response_shape_for_pause_type(
    run_service: RunService,
    fake_executor: FakeRunExecutor,
    created_run: Run,
    pause_kind: str,
    response: dict[str, object],
) -> None:
    await fake_executor.start(created_run.id)
    if pause_kind == "input":
        await fake_executor.pause_for_input(created_run.id, {"question": "成本价？"})
    else:
        await fake_executor.pause_for_approval(created_run.id, {"action": "place-order"})

    with pytest.raises(ResumeNotAllowed, match="response"):
        await run_service.resume_run(
            created_run.tenant_id,
            created_run.id,
            created_run.created_by_user_id,
            response=response,
        )


@pytest.mark.asyncio
async def test_lifecycle_mutation_preserves_invisible_as_not_found(
    run_service: RunService,
    created_run: Run,
    lifecycle_context: tuple[Tenant, User, User],
) -> None:
    _tenant, _member, outsider = lifecycle_context

    with pytest.raises(ResourceNotFound):
        await run_service.cancel_run(created_run.tenant_id, created_run.id, outsider.id)


@pytest.mark.asyncio
async def test_get_pause_preserves_invisible_as_not_found(
    run_service: RunService,
    fake_executor: FakeRunExecutor,
    created_run: Run,
    lifecycle_context: tuple[Tenant, User, User],
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant, _member, outsider = lifecycle_context
    await fake_executor.start(created_run.id)
    pause = await fake_executor.pause_for_input(created_run.id, {"question": "secret"})

    suffix = uuid.uuid4().hex[:12]
    other_member = User(
        username=f"other-{suffix}",
        email=f"other-{suffix}@example.com",
        hashed_password="test-password-hash",
    )
    async with async_session_factory() as session, session.begin():
        session.add(other_member)
        await session.flush()
        session.add(TenantMembership(tenant_id=tenant.id, user_id=other_member.id, role="member"))

    with pytest.raises(ResourceNotFound):
        await run_service.get_pause(
            created_run.tenant_id,
            created_run.id,
            outsider.id,
            pause.id,
        )
    with pytest.raises(ResourceNotFound):
        await run_service.get_pause(
            created_run.tenant_id,
            created_run.id,
            other_member.id,
            pause.id,
        )


@pytest.mark.asyncio
async def test_transition_event_cannot_spoof_authoritative_status_fields(
    run_service: RunService,
    created_run: Run,
) -> None:
    await run_service.transition_run(
        created_run.tenant_id,
        created_run.id,
        created_run.created_by_user_id,
        RunStatus.ASSIGNED,
        event_type="run.assigned",
        payload={"from_status": "failed", "status": "completed", "worker": "fake"},
    )

    events = await run_service.list_events(
        created_run.tenant_id, created_run.id, created_run.created_by_user_id
    )
    assert events[-1].payload == {
        "from_status": RunStatus.QUEUED.value,
        "status": RunStatus.ASSIGNED.value,
        "worker": "fake",
    }


@pytest.mark.asyncio
async def test_two_concurrent_mutations_allocate_unique_monotonic_event_seq(
    run_service: RunService,
    created_run: Run,
) -> None:
    results = await asyncio.gather(
        run_service.transition_run(
            created_run.tenant_id,
            created_run.id,
            created_run.created_by_user_id,
            RunStatus.ASSIGNED,
            event_type="run.assigned",
        ),
        run_service.cancel_run(
            created_run.tenant_id,
            created_run.id,
            created_run.created_by_user_id,
        ),
        return_exceptions=True,
    )

    assert all(
        not isinstance(result, BaseException) or isinstance(result, InvalidRunTransition)
        for result in results
    )
    events = await run_service.list_events(
        created_run.tenant_id, created_run.id, created_run.created_by_user_id
    )
    seqs = [event.seq for event in events]
    assert seqs == list(range(1, len(seqs) + 1))
    assert len(seqs) == len(set(seqs))


@pytest.mark.asyncio
async def test_concurrent_resume_resolves_pause_once_and_is_idempotent(
    run_service: RunService,
    fake_executor: FakeRunExecutor,
    created_run: Run,
) -> None:
    await fake_executor.start(created_run.id)
    pause = await fake_executor.pause_for_input(created_run.id, {"question": "成本价？"})

    first, second = await asyncio.gather(
        run_service.resume_run(
            created_run.tenant_id,
            created_run.id,
            created_run.created_by_user_id,
            response={"text": "1500"},
        ),
        run_service.resume_run(
            created_run.tenant_id,
            created_run.id,
            created_run.created_by_user_id,
            response={"text": "1500"},
        ),
    )

    assert first.status == second.status == RunStatus.QUEUED.value
    assert (
        await run_service.get_pause(
            created_run.tenant_id,
            created_run.id,
            created_run.created_by_user_id,
            pause.id,
        )
    ).response_payload == {"text": "1500"}
    events = await run_service.list_events(
        created_run.tenant_id, created_run.id, created_run.created_by_user_id
    )
    assert [event.event_type for event in events].count("run.resumed") == 1


@pytest.mark.asyncio
async def test_resolved_resume_rejects_a_different_response(
    run_service: RunService,
    fake_executor: FakeRunExecutor,
    created_run: Run,
) -> None:
    await fake_executor.start(created_run.id)
    pause = await fake_executor.pause_for_input(created_run.id, {"question": "cost?"})
    await run_service.resume_run(
        created_run.tenant_id,
        created_run.id,
        created_run.created_by_user_id,
        response={"text": "1500"},
    )

    with pytest.raises(ResumeNotAllowed, match="different response"):
        await run_service.resume_run(
            created_run.tenant_id,
            created_run.id,
            created_run.created_by_user_id,
            response={"text": "1600"},
        )

    resolved = await run_service.get_pause(
        created_run.tenant_id, created_run.id, created_run.created_by_user_id, pause.id
    )
    assert resolved.response_payload == {"text": "1500"}


@pytest.mark.asyncio
async def test_concurrent_conflicting_resume_commits_one_canonical_response(
    run_service: RunService,
    fake_executor: FakeRunExecutor,
    created_run: Run,
) -> None:
    await fake_executor.start(created_run.id)
    pause = await fake_executor.pause_for_input(created_run.id, {"question": "cost?"})

    results = await asyncio.gather(
        run_service.resume_run(
            created_run.tenant_id,
            created_run.id,
            created_run.created_by_user_id,
            response={"text": "1500"},
        ),
        run_service.resume_run(
            created_run.tenant_id,
            created_run.id,
            created_run.created_by_user_id,
            response={"text": "1600"},
        ),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, BaseException) for result in results) == 1
    conflicts = [result for result in results if isinstance(result, ResumeNotAllowed)]
    assert len(conflicts) == 1
    assert "different response" in str(conflicts[0])
    resolved = await run_service.get_pause(
        created_run.tenant_id, created_run.id, created_run.created_by_user_id, pause.id
    )
    assert resolved.response_payload in ({"text": "1500"}, {"text": "1600"})


@pytest.mark.asyncio
async def test_approval_decisions_must_exactly_cover_requested_call_ids_before_resolution(
    run_service: RunService,
    fake_executor: FakeRunExecutor,
    created_run: Run,
) -> None:
    await fake_executor.start(created_run.id)
    pause = await fake_executor.pause_for_approval(
        created_run.id,
        {"tool_calls": [{"id": "risky", "name": "place_order", "arguments": "{}"}]},
        {
            "version": 1,
            "body": {
                "pending_action": {
                    "pause_type": "approval",
                    "pending_tool_calls": [
                        {"id": "safe", "name": "search_tools", "arguments": "{}"},
                        {"id": "risky", "name": "place_order", "arguments": "{}"},
                    ],
                }
            },
        },
    )

    for decisions in ({"safe": True, "risky": True}, {}, {"wrong": True}):
        with pytest.raises(ResumeNotAllowed):
            await run_service.resume_run(
                created_run.tenant_id,
                created_run.id,
                created_run.created_by_user_id,
                response={"decisions": decisions},
            )
        unresolved = await run_service.get_pause(
            created_run.tenant_id, created_run.id, created_run.created_by_user_id, pause.id
        )
        assert unresolved.resolved_at is None
        assert unresolved.response_payload is None

    resumed = await run_service.resume_run(
        created_run.tenant_id,
        created_run.id,
        created_run.created_by_user_id,
        response={"decisions": {"risky": False}},
    )
    assert resumed.status == RunStatus.QUEUED.value


@pytest.mark.asyncio
async def test_cancel_racing_resume_finishes_in_legal_state(
    run_service: RunService,
    fake_executor: FakeRunExecutor,
    created_run: Run,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await fake_executor.start(created_run.id)
    await fake_executor.pause_for_approval(created_run.id, {"action": "place-order"})

    results = await asyncio.gather(
        run_service.cancel_run(
            created_run.tenant_id,
            created_run.id,
            created_run.created_by_user_id,
        ),
        run_service.resume_run(
            created_run.tenant_id,
            created_run.id,
            created_run.created_by_user_id,
            response={"approved": True},
        ),
        return_exceptions=True,
    )

    assert all(
        not isinstance(result, BaseException) or isinstance(result, ResumeNotAllowed)
        for result in results
    )
    current = await run_service.get_run(
        created_run.tenant_id, created_run.id, created_run.created_by_user_id
    )
    assert current.status == RunStatus.CANCELLED.value
    async with async_session_factory() as session:
        events = tuple(
            (
                await session.scalars(
                    select(RunEvent).where(RunEvent.run_id == created_run.id).order_by(RunEvent.seq)
                )
            ).all()
        )
    assert [event.seq for event in events] == list(range(1, len(events) + 1))


@pytest.mark.asyncio
async def test_record_pause_requires_running(
    fake_executor: FakeRunExecutor, created_run: Run
) -> None:
    with pytest.raises(InvalidRunTransition):
        await fake_executor.pause_for_input(created_run.id, {"question": "too early"})
