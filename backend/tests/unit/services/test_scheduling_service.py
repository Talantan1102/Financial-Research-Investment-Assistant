from __future__ import annotations

import asyncio
import os
import sys
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
import pytest_asyncio
from app.core.database import Base
from app.models.run import Run, RunAttempt, RunEvent, RunMessage, RunPause, RunSession
from app.models.run_scheduling import RunOutbox, RunTenantScheduling, RunWorker
from app.models.tenant import Tenant
from app.models.user import User
from app.run_control.scheduling_policy import WorkerCandidate
from app.services import scheduling_service as scheduling_module
from app.services.run_metrics import RunMetricsService
from app.services.scheduling_service import Assignment, SchedulingService
from sqlalchemy import delete, event, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture(scope="module")
async def async_session_factory(
    pg_test_container: dict[str, object],
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Give Scheduler concurrency tests an isolated real-PostgreSQL schema."""

    del pg_test_container
    from tests.pg_test_defaults import PG_PASSWORD_DEFAULT

    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", PG_PASSWORD_DEFAULT)
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    database = os.getenv("POSTGRES_DB", "industry_assistant_test")
    url = f"postgresql+psycopg://{user}:{password}@{host}:{port}/{database}"
    schema = f"scheduling_service_{uuid.uuid4().hex}"
    admin_engine = create_async_engine(url, future=True)
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    engine = create_async_engine(
        url,
        future=True,
        connect_args={"options": f"-c search_path={schema}"},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin_engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def cleanup_scheduling_rows(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[None]:
    async with async_session_factory() as session:
        tenant_ids = set((await session.scalars(select(Tenant.id))).all())
        user_ids = set((await session.scalars(select(User.id))).all())
        worker_ids = set((await session.scalars(select(RunWorker.id))).all())
    try:
        yield
    finally:
        async with async_session_factory() as session, session.begin():
            created_tenant_ids = set((await session.scalars(select(Tenant.id))).all()) - tenant_ids
            created_user_ids = set((await session.scalars(select(User.id))).all()) - user_ids
            created_worker_ids = (
                set((await session.scalars(select(RunWorker.id))).all()) - worker_ids
            )
            if created_tenant_ids:
                run_ids = select(Run.id).where(Run.tenant_id.in_(created_tenant_ids))
                await session.execute(delete(RunEvent).where(RunEvent.run_id.in_(run_ids)))
                await session.execute(delete(RunOutbox).where(RunOutbox.run_id.in_(run_ids)))
                await session.execute(delete(RunAttempt).where(RunAttempt.run_id.in_(run_ids)))
                await session.execute(delete(Tenant).where(Tenant.id.in_(created_tenant_ids)))
            if created_worker_ids:
                await session.execute(delete(RunWorker).where(RunWorker.id.in_(created_worker_ids)))
            if created_user_ids:
                await session.execute(delete(User).where(User.id.in_(created_user_ids)))


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
            id=tenant_id or uuid.UUID(int=1),
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
                revision_seq=1,
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
    worker_id: uuid.UUID | None = None,
) -> RunWorker:
    async with factory() as session, session.begin():
        now = func.timezone("UTC", func.statement_timestamp())
        worker = RunWorker(
            id=worker_id or uuid.UUID(int=1000),
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


async def _create_cursors(
    factory: async_sessionmaker[AsyncSession],
    tenant_ids: Sequence[uuid.UUID],
) -> None:
    async with factory() as session, session.begin():
        session.add_all([RunTenantScheduling(tenant_id=tenant_id) for tenant_id in tenant_ids])


class TwoPartyBarrier:
    def __init__(self) -> None:
        self._arrivals = 0
        self._guard = asyncio.Lock()
        self._release = asyncio.Event()

    async def wait(self) -> None:
        async with self._guard:
            self._arrivals += 1
            if self._arrivals == 2:
                self._release.set()
        await self._release.wait()


class ReverseFallbackSchedulingService(SchedulingService):
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        *,
        candidates: tuple[WorkerCandidate, ...],
        first_worker_id: uuid.UUID,
        barrier: TwoPartyBarrier,
    ) -> None:
        super().__init__(factory)
        self._test_candidates = candidates
        self._test_first_worker_id = first_worker_id
        self._test_barrier = barrier

    async def _load_worker_candidates(self, session: AsyncSession) -> tuple[WorkerCandidate, ...]:
        del session
        return self._test_candidates

    async def _lock_worker_candidate(
        self, session: AsyncSession, worker_id: uuid.UUID
    ) -> RunWorker | None:
        worker = await super()._lock_worker_candidate(session, worker_id)
        if worker_id == self._test_first_worker_id:
            await self._test_barrier.wait()
        return worker


class CursorBarrierSchedulingService(SchedulingService):
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        barrier: TwoPartyBarrier,
    ) -> None:
        super().__init__(factory)
        self._test_barrier = barrier

    async def _lock_next_tenant_cursor(self, session: AsyncSession) -> RunTenantScheduling | None:
        await self._test_barrier.wait()
        return await super()._lock_next_tenant_cursor(session)


class CursorBootstrapBarrierSchedulingService(SchedulingService):
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        barrier: TwoPartyBarrier,
    ) -> None:
        super().__init__(factory)
        self._test_barrier = barrier

    async def _ensure_tenant_cursors(self, session: AsyncSession) -> None:
        await self._test_barrier.wait()
        await super()._ensure_tenant_cursors(session)


class WorkerBarrierSchedulingService(SchedulingService):
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        barrier: TwoPartyBarrier,
    ) -> None:
        super().__init__(factory)
        self._test_barrier = barrier

    async def _lock_eligible_worker(
        self,
        session: AsyncSession,
        candidates: tuple[WorkerCandidate, ...],
    ) -> tuple[RunWorker, int] | None:
        await self._test_barrier.wait()
        return await super()._lock_eligible_worker(session, candidates)


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
            revision_seq=1,
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
async def test_no_worker_does_not_persist_cursor_side_effect(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    queue = await _create_queue(
        async_session_factory,
        queued_at=[datetime(2026, 7, 17, 1)],
    )

    assert await _service(async_session_factory).schedule_once() is None

    async with async_session_factory() as session:
        assert await session.get(RunTenantScheduling, queue.tenant_id) is None


@pytest.mark.asyncio
async def test_no_worker_persists_block_reason_without_cursor_side_effect(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    queue = await _create_queue(
        async_session_factory,
        queued_at=[datetime(2026, 7, 17, 1)],
    )

    assert await _service(async_session_factory).schedule_once() is None

    async with async_session_factory() as session:
        run = await session.get(Run, queue.runs[0].id)
        event = await session.scalar(
            select(RunEvent).where(
                RunEvent.run_id == queue.runs[0].id,
                RunEvent.event_type == "run.queue_blocked",
            )
        )
        cursor = await session.get(RunTenantScheduling, queue.tenant_id)
    assert run is not None and run.queue_reason == "no_worker_capacity"
    assert event is not None and event.payload["reason"] == "no_worker_capacity"
    assert cursor is None


@pytest.mark.asyncio
async def test_no_assignment_keeps_existing_cursor_timestamps_unchanged(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    queue = await _create_queue(
        async_session_factory,
        queued_at=[datetime(2026, 7, 17, 1)],
    )
    original_dispatch = datetime(2026, 7, 16, 1)
    original_update = datetime(2026, 7, 16, 2)
    async with async_session_factory() as session, session.begin():
        session.add(
            RunTenantScheduling(
                tenant_id=queue.tenant_id,
                last_dispatched_at=original_dispatch,
                updated_at=original_update,
            )
        )

    assert await _service(async_session_factory).schedule_once() is None

    async with async_session_factory() as session:
        cursor = await session.get(RunTenantScheduling, queue.tenant_id)
    assert cursor is not None
    assert (cursor.last_dispatched_at, cursor.updated_at) == (
        original_dispatch,
        original_update,
    )


@pytest.mark.asyncio
async def test_cursor_bootstrap_is_one_statement_and_worker_snapshot_is_read_once(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 7, 17, 1)
    for offset in range(3):
        await _create_queue(
            async_session_factory,
            queued_at=[now],
            tenant_id=uuid.UUID(int=offset + 1),
        )
    await _create_worker(async_session_factory, capacity=3)
    statements: list[str] = []
    sync_engine = cast(Any, async_session_factory.kw["bind"]).sync_engine

    def capture_sql(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        normalized = " ".join(statement.lower().split())
        if "insert into run_tenant_scheduling" in normalized or (
            "from run_attempts" in normalized
            and "group by run_attempts.worker_id" in normalized
            and "run_workers" in normalized
        ):
            statements.append(normalized)

    event.listen(sync_engine, "before_cursor_execute", capture_sql)
    try:
        assert await _service(async_session_factory).schedule_once() is not None
    finally:
        event.remove(sync_engine, "before_cursor_execute", capture_sql)

    cursor_inserts = [sql for sql in statements if "insert into run_tenant_scheduling" in sql]
    worker_snapshots = [sql for sql in statements if "group by run_attempts.worker_id" in sql]
    assert len(cursor_inserts) == 1
    assert "select distinct runs.tenant_id" in cursor_inserts[0]
    assert "order by runs.tenant_id" in cursor_inserts[0]
    assert len(worker_snapshots) == 1


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
async def test_assignment_clears_stale_scheduler_block_reason(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    queue = await _create_queue(
        async_session_factory,
        queued_at=[datetime(2026, 7, 17, 1)],
        queue_reasons=["no_worker_capacity"],
    )
    await _create_worker(async_session_factory, capacity=1)

    assignment = await _service(async_session_factory).schedule_once()

    assert assignment is not None
    async with async_session_factory() as session:
        run = await session.get(Run, queue.runs[0].id)
    assert run is not None and run.queue_reason is None


@pytest.mark.asyncio
async def test_no_worker_then_success_removes_reason_from_metrics_window(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    queue = await _create_queue(
        async_session_factory,
        queued_at=[datetime(2026, 7, 17, 1)],
    )
    service = _service(async_session_factory)

    assert await service.schedule_once() is None
    await _create_worker(async_session_factory, capacity=1)
    assert await service.schedule_once() is not None

    metrics = await RunMetricsService(async_session_factory).snapshot(queue.tenant_id)
    # no_slot is a windowed count of persisted scheduler blocking facts.  The
    # later successful assignment clears the current Run.queue_reason but does
    # not erase the historical run.queue_blocked event.
    assert metrics["scheduling"]["no_slot"] == 1


@pytest.mark.asyncio
async def test_two_schedulers_assign_one_run_once(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    queue = await _create_queue(async_session_factory, queued_at=[datetime(2026, 7, 17, 1)])
    await _create_worker(async_session_factory, capacity=2)
    await _create_cursors(async_session_factory, [queue.tenant_id])
    barrier = TwoPartyBarrier()

    results = await asyncio.wait_for(
        asyncio.gather(
            CursorBarrierSchedulingService(async_session_factory, barrier).schedule_once(),
            CursorBarrierSchedulingService(async_session_factory, barrier).schedule_once(),
        ),
        timeout=2,
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
async def test_two_schedulers_create_missing_cursors_concurrently_without_deadlock(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 7, 17, 1)
    queues = [
        await _create_queue(
            async_session_factory,
            queued_at=[now],
            tenant_id=uuid.UUID(int=offset),
        )
        for offset in (1, 2)
    ]
    await _create_worker(async_session_factory, capacity=2)
    barrier = TwoPartyBarrier()

    results = await asyncio.wait_for(
        asyncio.gather(
            CursorBootstrapBarrierSchedulingService(async_session_factory, barrier).schedule_once(),
            CursorBootstrapBarrierSchedulingService(async_session_factory, barrier).schedule_once(),
        ),
        timeout=2,
    )

    assert sum(result is not None for result in results) == 2
    async with async_session_factory() as session:
        cursor_count = await session.scalar(
            select(func.count())
            .select_from(RunTenantScheduling)
            .where(RunTenantScheduling.tenant_id.in_([item.tenant_id for item in queues]))
        )
    assert cursor_count == 2


@pytest.mark.asyncio
async def test_two_schedulers_do_not_oversell_worker_capacity(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 7, 17, 1)
    first = await _create_queue(
        async_session_factory,
        queued_at=[now],
        tenant_id=uuid.UUID(int=1),
    )
    second = await _create_queue(
        async_session_factory,
        queued_at=[now],
        tenant_id=uuid.UUID(int=2),
    )
    worker = await _create_worker(async_session_factory, capacity=1)
    await _create_cursors(
        async_session_factory,
        [first.tenant_id, second.tenant_id],
    )
    barrier = TwoPartyBarrier()

    results = await asyncio.wait_for(
        asyncio.gather(
            WorkerBarrierSchedulingService(async_session_factory, barrier).schedule_once(),
            WorkerBarrierSchedulingService(async_session_factory, barrier).schedule_once(),
        ),
        timeout=2,
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
    queues = [
        await _create_queue(
            async_session_factory,
            tenant_id=uuid.UUID(int=offset),
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
    await _create_worker(
        async_session_factory,
        capacity=1,
        status="draining",
        worker_id=uuid.UUID(int=1001),
    )

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

    async def drain_after_snapshot(
        session: AsyncSession,
        *,
        heartbeat_ttl: timedelta,
    ) -> object:
        nonlocal calls
        snapshots = await original(session, heartbeat_ttl=heartbeat_ttl)
        calls += 1
        if calls == 1:
            async with async_session_factory() as writer, writer.begin():
                await writer.execute(
                    update(RunWorker).where(RunWorker.id == worker.id).values(status="draining")
                )
        return snapshots

    monkeypatch.setattr(
        scheduling_module,
        "load_schedulable_workers",
        drain_after_snapshot,
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
    assert run.queue_reason == "no_worker_capacity"
    assert attempt_count == 0


@pytest.mark.asyncio
async def test_opposite_stale_worker_fallback_orders_do_not_deadlock(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 7, 17, 1)
    first_queue = await _create_queue(
        async_session_factory,
        queued_at=[now],
        tenant_id=uuid.UUID(int=1),
    )
    second_queue = await _create_queue(
        async_session_factory,
        queued_at=[now],
        tenant_id=uuid.UUID(int=2),
    )
    await _create_cursors(
        async_session_factory,
        [first_queue.tenant_id, second_queue.tenant_id],
    )
    first_worker = await _create_worker(
        async_session_factory,
        capacity=1,
        status="draining",
        worker_id=uuid.uuid4(),
    )
    second_worker = await _create_worker(
        async_session_factory,
        capacity=1,
        status="draining",
        worker_id=uuid.uuid4(),
    )
    candidates = {
        cast(uuid.UUID, first_worker.id): WorkerCandidate(
            id=cast(uuid.UUID, first_worker.id),
            capacity=1,
            active_attempts=0,
            last_assigned_at=None,
        ),
        cast(uuid.UUID, second_worker.id): WorkerCandidate(
            id=cast(uuid.UUID, second_worker.id),
            capacity=1,
            active_attempts=0,
            last_assigned_at=None,
        ),
    }
    first_worker_id = cast(uuid.UUID, first_worker.id)
    second_worker_id = cast(uuid.UUID, second_worker.id)
    barrier = TwoPartyBarrier()
    first = ReverseFallbackSchedulingService(
        async_session_factory,
        candidates=(candidates[first_worker_id], candidates[second_worker_id]),
        first_worker_id=first_worker_id,
        barrier=barrier,
    )
    second = ReverseFallbackSchedulingService(
        async_session_factory,
        candidates=(candidates[second_worker_id], candidates[first_worker_id]),
        first_worker_id=second_worker_id,
        barrier=barrier,
    )

    results = await asyncio.wait_for(
        asyncio.gather(first.schedule_once(), second.schedule_once()),
        timeout=1,
    )

    assert results == [None, None]


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
    async with async_session_factory() as session:
        run = await session.get(Run, queue.runs[0].id)
        event = await session.scalar(
            select(RunEvent).where(
                RunEvent.run_id == queue.runs[0].id,
                RunEvent.event_type == "run.queue_blocked",
            )
        )
    assert run is not None and run.queue_reason == "tenant_at_capacity"
    assert event is not None and event.payload["reason"] == "tenant_at_capacity"


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
async def test_non_whitelisted_outbox_unique_conflict_reraises_and_rolls_back(
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

    with pytest.raises(IntegrityError) as captured:
        await _service(async_session_factory).schedule_once()

    original = cast(Any, captured.value.orig)
    assert original.diag.constraint_name == "uq_run_outbox_dedupe_key"

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
