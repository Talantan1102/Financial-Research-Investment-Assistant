from __future__ import annotations

import asyncio
import sys
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
import pytest_asyncio
from app.models.run import Run, RunAttempt, RunEvent, RunMessage, RunPause, RunSession
from app.models.run_scheduling import RunOutbox, RunTenantScheduling, RunWorker
from app.models.tenant import Tenant
from app.models.user import User
from app.services import scheduling_service as scheduling_module
from app.services.scheduling_service import Assignment, SchedulingService
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture(autouse=True)
async def cleanup_scheduling_rows(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[None]:
    await _purge_scheduler_test_rows(async_session_factory)
    async with async_session_factory() as session, session.begin():
        queued_run_ids = tuple(
            (await session.scalars(select(Run.id).where(Run.status == "queued"))).all()
        )
        worker_statuses: dict[uuid.UUID, str] = {
            cast(uuid.UUID, worker_id): cast(str, status)
            for worker_id, status in (
                await session.execute(select(RunWorker.id, RunWorker.status))
            ).all()
        }
        if queued_run_ids:
            await session.execute(
                update(Run).where(Run.id.in_(queued_run_ids)).values(status="cancelled")
            )
        if worker_statuses:
            await session.execute(
                update(RunWorker).where(RunWorker.id.in_(worker_statuses)).values(status="offline")
            )
    try:
        yield
    finally:
        await _purge_scheduler_test_rows(async_session_factory)
        async with async_session_factory() as session, session.begin():
            if queued_run_ids:
                await session.execute(
                    update(Run).where(Run.id.in_(queued_run_ids)).values(status="queued")
                )
            for worker_id, status in worker_statuses.items():
                await session.execute(
                    update(RunWorker).where(RunWorker.id == worker_id).values(status=status)
                )


async def _purge_scheduler_test_rows(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """Remove only rows created by this test module, including aborted prior runs."""

    run_ids = (
        select(Run.id)
        .join(Tenant, Tenant.id == Run.tenant_id)
        .where(Tenant.slug.like("scheduler-%"))
    )
    async with factory() as session, session.begin():
        worker_ids = set(
            (
                await session.scalars(
                    select(RunAttempt.worker_id).where(
                        RunAttempt.run_id.in_(run_ids),
                        RunAttempt.worker_id.is_not(None),
                    )
                )
            ).all()
        )
        worker_ids.update(
            (
                await session.scalars(
                    select(RunWorker.id).where(
                        RunWorker.metadata_payload.contains({"test_suite": "scheduling_service"})
                    )
                )
            ).all()
        )
        await session.execute(delete(RunEvent).where(RunEvent.run_id.in_(run_ids)))
        await session.execute(delete(RunOutbox).where(RunOutbox.run_id.in_(run_ids)))
        await session.execute(delete(RunAttempt).where(RunAttempt.run_id.in_(run_ids)))
        await session.execute(delete(Tenant).where(Tenant.slug.like("scheduler-%")))
        if worker_ids:
            await session.execute(
                update(RunWorker).where(RunWorker.id.in_(worker_ids)).values(status="offline")
            )
        await session.execute(delete(User).where(User.username.like("scheduler-%")))


@dataclass(frozen=True)
class QueueFixture:
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    runs: tuple[Run, ...]


async def _create_queue(
    factory: async_sessionmaker[AsyncSession],
    *,
    queued_at: Sequence[datetime],
    queue_reasons: Sequence[str | None] | None = None,
    tenant_id: uuid.UUID | None = None,
    max_running_runs: int = 10,
) -> QueueFixture:
    suffix = uuid.uuid4().hex
    reasons = queue_reasons or [None] * len(queued_at)
    assert len(reasons) == len(queued_at)
    async with factory() as session, session.begin():
        user = User(
            username=f"scheduler-{suffix}",
            email=f"scheduler-{suffix}@example.com",
            hashed_password="test-password-hash",
        )
        tenant = Tenant(
            id=tenant_id or uuid.uuid4(),
            name=f"Scheduler {suffix}",
            slug=f"scheduler-{suffix}",
            max_running_runs=max_running_runs,
        )
        session.add_all([user, tenant])
        await session.flush()
        runs: list[Run] = []
        for index, (queued, reason) in enumerate(zip(queued_at, reasons, strict=True)):
            run_session = RunSession(tenant_id=tenant.id, created_by_user_id=user.id)
            session.add(run_session)
            await session.flush()
            message = RunMessage(
                tenant_id=tenant.id,
                session_id=run_session.id,
                role="user",
                content=f"prompt-{index}",
                status="complete",
            )
            session.add(message)
            await session.flush()
            run = Run(
                tenant_id=tenant.id,
                session_id=run_session.id,
                created_by_user_id=user.id,
                run_type="chat",
                status="queued",
                idempotency_key=f"scheduler-{suffix}-{index}",
                request_hash=uuid.uuid4().hex,
                input_message_id=message.id,
                retry_count=0,
                queue_reason=reason,
                queued_at=queued,
            )
            session.add(run)
            await session.flush()
            session.add(
                RunEvent(
                    tenant_id=tenant.id,
                    run_id=run.id,
                    seq=1,
                    event_type="run.created",
                    payload={"status": "queued"},
                )
            )
            runs.append(run)
    return QueueFixture(
        tenant_id=cast(uuid.UUID, tenant.id),
        user_id=cast(uuid.UUID, user.id),
        runs=tuple(runs),
    )


async def _create_worker(
    factory: async_sessionmaker[AsyncSession],
    *,
    capacity: int,
    status: str = "online",
    heartbeat_delta: timedelta = timedelta(0),
) -> RunWorker:
    async with factory() as session, session.begin():
        now = func.timezone("UTC", func.statement_timestamp())
        worker = RunWorker(
            worker_type="chat",
            capacity=capacity,
            status=status,
            heartbeat_at=now + heartbeat_delta,
            started_at=now,
            metadata_payload={"test_suite": "scheduling_service"},
        )
        session.add(worker)
        await session.flush()
    return worker


async def _create_active_run(
    factory: async_sessionmaker[AsyncSession],
    queue: QueueFixture,
) -> Run:
    suffix = uuid.uuid4().hex
    async with factory() as session, session.begin():
        run_session = RunSession(
            tenant_id=queue.tenant_id,
            created_by_user_id=queue.user_id,
        )
        session.add(run_session)
        await session.flush()
        message = RunMessage(
            tenant_id=queue.tenant_id,
            session_id=run_session.id,
            role="user",
            content="active",
            status="complete",
        )
        session.add(message)
        await session.flush()
        run = Run(
            tenant_id=queue.tenant_id,
            session_id=run_session.id,
            created_by_user_id=queue.user_id,
            run_type="chat",
            status="assigned",
            idempotency_key=f"scheduler-active-{suffix}",
            request_hash=uuid.uuid4().hex,
            input_message_id=message.id,
            retry_count=0,
        )
        session.add(run)
        await session.flush()
    return run


def _service(factory: async_sessionmaker[AsyncSession]) -> SchedulingService:
    return SchedulingService(
        factory,
        heartbeat_ttl=timedelta(seconds=30),
        lease_duration=timedelta(seconds=45),
        resume_priority_boost_seconds=30,
    )


@pytest.mark.asyncio
async def test_schedule_once_atomically_writes_assignment_graph(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    queue = await _create_queue(async_session_factory, queued_at=[datetime(2026, 7, 17, 1)])
    worker = await _create_worker(async_session_factory, capacity=2)

    assignment = await _service(async_session_factory).schedule_once()

    assert assignment is not None
    assert (assignment.run_id, assignment.worker_id) == (queue.runs[0].id, worker.id)
    async with async_session_factory() as session:
        run = await session.get(Run, assignment.run_id)
        attempt = await session.get(RunAttempt, assignment.attempt_id)
        outbox = await session.scalar(
            select(RunOutbox).where(RunOutbox.attempt_id == assignment.attempt_id)
        )
        event = await session.scalar(
            select(RunEvent).where(
                RunEvent.run_id == assignment.run_id,
                RunEvent.event_type == "run.assigned",
            )
        )
        cursor = await session.get(RunTenantScheduling, queue.tenant_id)
        persisted_worker = await session.get(RunWorker, worker.id)
    assert run is not None and run.status == "assigned"
    assert attempt is not None
    assert (attempt.attempt_no, attempt.status, attempt.worker_id) == (1, "assigned", worker.id)
    assert attempt.lease_expires_at == assignment.lease_expires_at
    assert outbox is not None
    assert outbox.event_type == "attempt.assigned"
    assert outbox.dedupe_key == f"attempt-assigned:{assignment.attempt_id}"
    assert outbox.payload == {
        "attempt_id": str(assignment.attempt_id),
        "run_id": str(assignment.run_id),
        "tenant_id": str(queue.tenant_id),
        "worker_id": str(worker.id),
    }
    assert event is not None and event.attempt_id == assignment.attempt_id
    assert cursor is not None and cursor.last_dispatched_at is not None
    assert persisted_worker is not None
    assert persisted_worker.last_assigned_at == cursor.last_dispatched_at


@pytest.mark.asyncio
async def test_two_schedulers_assign_one_run_once(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    queue = await _create_queue(async_session_factory, queued_at=[datetime(2026, 7, 17, 1)])
    await _create_worker(async_session_factory, capacity=2)

    results = await asyncio.gather(
        _service(async_session_factory).schedule_once(),
        _service(async_session_factory).schedule_once(),
    )

    assert sum(result is not None for result in results) == 1
    async with async_session_factory() as session:
        attempts = await session.scalar(
            select(func.count())
            .select_from(RunAttempt)
            .where(RunAttempt.run_id == queue.runs[0].id)
        )
    assert attempts == 1


@pytest.mark.asyncio
async def test_two_schedulers_do_not_oversell_worker_capacity(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 7, 17, 1)
    first = await _create_queue(async_session_factory, queued_at=[now])
    second = await _create_queue(async_session_factory, queued_at=[now])
    worker = await _create_worker(async_session_factory, capacity=1)

    results = await asyncio.gather(
        _service(async_session_factory).schedule_once(),
        _service(async_session_factory).schedule_once(),
    )

    assert sum(result is not None for result in results) == 1
    async with async_session_factory() as session:
        live = await session.scalar(
            select(func.count())
            .select_from(RunAttempt)
            .where(RunAttempt.worker_id == worker.id, RunAttempt.status == "assigned")
        )
        queued = await session.scalar(
            select(func.count())
            .select_from(Run)
            .where(Run.id.in_([first.runs[0].id, second.runs[0].id]), Run.status == "queued")
        )
    assert (live, queued) == (1, 1)


@pytest.mark.asyncio
async def test_tenant_round_robin_is_a1_b1_c1_a2(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 7, 17, 1)
    base = uuid.uuid4().int & ~0xFF
    queues = [
        await _create_queue(
            async_session_factory,
            tenant_id=uuid.UUID(int=base + offset),
            queued_at=[now, now + timedelta(seconds=1)],
        )
        for offset in (1, 2, 3)
    ]
    await _create_worker(async_session_factory, capacity=10)

    assignments = [await _service(async_session_factory).schedule_once() for _ in range(4)]

    run_to_tenant = {
        cast(uuid.UUID, run.id): queue.tenant_id for queue in queues for run in queue.runs
    }
    assert all(item is not None for item in assignments)
    tenant_order = [run_to_tenant[cast(Assignment, item).run_id] for item in assignments]
    assert tenant_order == [
        queues[0].tenant_id,
        queues[1].tenant_id,
        queues[2].tenant_id,
        queues[0].tenant_id,
    ]


@pytest.mark.asyncio
async def test_tenant_priority_is_fifo_with_finite_resume_boost(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 7, 17, 1)
    queue = await _create_queue(
        async_session_factory,
        queued_at=[now, now + timedelta(seconds=20), now + timedelta(seconds=31)],
        queue_reasons=[None, "resume", "resume"],
    )
    await _create_worker(async_session_factory, capacity=10)

    assignments = [await _service(async_session_factory).schedule_once() for _ in range(3)]

    assert [item.run_id for item in assignments if item is not None] == [
        queue.runs[1].id,
        queue.runs[0].id,
        queue.runs[2].id,
    ]


@pytest.mark.asyncio
async def test_stale_and_draining_workers_are_rejected_after_candidate_read(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _create_queue(async_session_factory, queued_at=[datetime(2026, 7, 17, 1)])
    await _create_worker(
        async_session_factory,
        capacity=1,
        heartbeat_delta=timedelta(minutes=-1),
    )
    await _create_worker(async_session_factory, capacity=1, status="draining")

    assert await _service(async_session_factory).schedule_once() is None


@pytest.mark.asyncio
async def test_worker_is_rechecked_after_snapshot_before_assignment(
    async_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = await _create_queue(
        async_session_factory,
        queued_at=[datetime(2026, 7, 17, 1)],
    )
    worker = await _create_worker(async_session_factory, capacity=1)
    original = scheduling_module.load_schedulable_workers
    calls = 0

    async def drain_after_second_snapshot(
        session: AsyncSession,
        *,
        heartbeat_ttl: timedelta,
    ) -> object:
        nonlocal calls
        snapshots = await original(session, heartbeat_ttl=heartbeat_ttl)
        calls += 1
        if calls == 2:
            async with async_session_factory() as writer, writer.begin():
                await writer.execute(
                    update(RunWorker).where(RunWorker.id == worker.id).values(status="draining")
                )
        return snapshots

    monkeypatch.setattr(
        scheduling_module,
        "load_schedulable_workers",
        drain_after_second_snapshot,
    )

    assert await _service(async_session_factory).schedule_once() is None
    async with async_session_factory() as session:
        run = await session.get(Run, queue.runs[0].id)
        attempt_count = await session.scalar(
            select(func.count())
            .select_from(RunAttempt)
            .where(RunAttempt.run_id == queue.runs[0].id)
        )
    assert run is not None and run.status == "queued"
    assert attempt_count == 0


@pytest.mark.asyncio
async def test_tenant_at_running_limit_is_not_scheduled(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    queue = await _create_queue(
        async_session_factory,
        queued_at=[datetime(2026, 7, 17, 1)],
        max_running_runs=1,
    )
    await _create_active_run(async_session_factory, queue)
    await _create_worker(async_session_factory, capacity=2)

    assert await _service(async_session_factory).schedule_once() is None


@pytest.mark.asyncio
async def test_unresolved_pause_tenant_capacity_and_cancel_marker_are_ineligible(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    queue = await _create_queue(
        async_session_factory,
        queued_at=[datetime(2026, 7, 17, 1)],
        max_running_runs=1,
    )
    run = queue.runs[0]
    async with async_session_factory() as session, session.begin():
        session.add(
            RunPause(
                run_id=run.id,
                pause_no=1,
                pause_type="input",
                request_payload={},
                continuation_payload={},
            )
        )
    await _create_worker(async_session_factory, capacity=1)
    assert await _service(async_session_factory).schedule_once() is None

    async with async_session_factory() as session, session.begin():
        pause = await session.scalar(select(RunPause).where(RunPause.run_id == run.id))
        assert pause is not None
        cast(Any, pause).resolved_at = func.timezone("UTC", func.statement_timestamp())
        run_row = await session.get(Run, run.id)
        assert run_row is not None
        cast(Any, run_row).cancel_requested_at = func.timezone("UTC", func.statement_timestamp())
    assert await _service(async_session_factory).schedule_once() is None


@pytest.mark.asyncio
async def test_attempt_number_uses_max_plus_one(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    queue = await _create_queue(async_session_factory, queued_at=[datetime(2026, 7, 17, 1)])
    async with async_session_factory() as session, session.begin():
        session.add(RunAttempt(run_id=queue.runs[0].id, attempt_no=1, status="lost"))
    await _create_worker(async_session_factory, capacity=1)

    assignment = await _service(async_session_factory).schedule_once()

    assert assignment is not None
    async with async_session_factory() as session:
        attempt = await session.get(RunAttempt, assignment.attempt_id)
    assert attempt is not None and attempt.attempt_no == 2


@pytest.mark.asyncio
async def test_outbox_conflict_rolls_back_run_attempt_event_worker_and_cursor(
    async_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = await _create_queue(async_session_factory, queued_at=[datetime(2026, 7, 17, 1)])
    worker = await _create_worker(async_session_factory, capacity=1)
    fixed_attempt_id = uuid.uuid4()
    async with async_session_factory() as session, session.begin():
        session.add(
            RunOutbox(
                event_type="schedule.wake",
                tenant_id=queue.tenant_id,
                run_id=queue.runs[0].id,
                payload={},
                dedupe_key=f"attempt-assigned:{fixed_attempt_id}",
            )
        )
    monkeypatch.setattr("app.services.scheduling_service.uuid4", lambda: fixed_attempt_id)

    assert await _service(async_session_factory).schedule_once() is None

    async with async_session_factory() as session:
        run = await session.get(Run, queue.runs[0].id)
        attempts = await session.scalar(
            select(func.count())
            .select_from(RunAttempt)
            .where(RunAttempt.run_id == queue.runs[0].id)
        )
        assigned_events = await session.scalar(
            select(func.count())
            .select_from(RunEvent)
            .where(
                RunEvent.run_id == queue.runs[0].id,
                RunEvent.event_type == "run.assigned",
            )
        )
        cursor = await session.get(RunTenantScheduling, queue.tenant_id)
        persisted_worker = await session.get(RunWorker, worker.id)
        outbox_count = await session.scalar(
            select(func.count()).select_from(RunOutbox).where(RunOutbox.run_id == queue.runs[0].id)
        )
    assert run is not None and run.status == "queued"
    assert (attempts, assigned_events, outbox_count) == (0, 0, 1)
    assert cursor is None
    assert persisted_worker is not None and persisted_worker.last_assigned_at is None


@pytest.mark.asyncio
async def test_non_unique_integrity_error_is_rolled_back_and_reraised(
    async_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = await _create_queue(
        async_session_factory,
        queued_at=[datetime(2026, 7, 17, 1)],
    )
    await _create_worker(async_session_factory, capacity=1)
    monkeypatch.setattr(
        scheduling_module,
        "OutboxType",
        SimpleNamespace(ATTEMPT_ASSIGNED=SimpleNamespace(value="invalid.outbox.type")),
    )

    with pytest.raises(IntegrityError, match="ck_run_outbox_fixed_type"):
        await _service(async_session_factory).schedule_once()

    async with async_session_factory() as session:
        run = await session.get(Run, queue.runs[0].id)
        attempts = await session.scalar(
            select(func.count())
            .select_from(RunAttempt)
            .where(RunAttempt.run_id == queue.runs[0].id)
        )
    assert run is not None and run.status == "queued"
    assert attempts == 0
