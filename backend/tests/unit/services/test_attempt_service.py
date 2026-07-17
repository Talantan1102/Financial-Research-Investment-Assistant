from __future__ import annotations

import asyncio
import os
import sys
import uuid
from collections.abc import AsyncIterator, Mapping
from datetime import timedelta
from typing import Any, cast

import pytest
import pytest_asyncio
from app.core.database import Base
from app.models.run import Run, RunAttempt, RunEvent, RunMessage, RunSession
from app.models.run_scheduling import RunOutbox, RunWorker
from app.models.tenant import Tenant
from app.models.user import User
from app.services.attempt_service import AttemptCommandRejected, AttemptService
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture(scope="module")
async def attempt_factory(
    pg_test_container: dict[str, object],
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    del pg_test_container
    from tests.pg_test_defaults import PG_PASSWORD_DEFAULT

    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", PG_PASSWORD_DEFAULT)
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    database = os.getenv("POSTGRES_DB", "industry_assistant_test")
    url = f"postgresql+psycopg://{user}:{password}@{host}:{port}/{database}"
    schema = f"attempt_service_{uuid.uuid4().hex}"
    admin_engine = create_async_engine(url, future=True)
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(url, connect_args={"options": f"-c search_path={schema}"})
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
async def cleanup_attempt_rows(
    attempt_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[None]:
    yield
    async with attempt_factory() as session, session.begin():
        await session.execute(delete(RunEvent))
        await session.execute(delete(RunOutbox))
        await session.execute(delete(RunAttempt))
        await session.execute(delete(Run))
        await session.execute(delete(RunWorker))
        await session.execute(delete(Tenant))
        await session.execute(delete(User))


class TwoPartyBarrier:
    def __init__(self) -> None:
        self._count = 0
        self._guard = asyncio.Lock()
        self._release = asyncio.Event()

    async def wait(self) -> None:
        async with self._guard:
            self._count += 1
            if self._count == 2:
                self._release.set()
        await self._release.wait()


class BarrierAttemptService(AttemptService):
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        barrier: TwoPartyBarrier,
    ) -> None:
        super().__init__(factory, lease_duration=timedelta(seconds=30))
        self._barrier = barrier

    async def _before_attempt_lock(self) -> None:
        await self._barrier.wait()


async def _assigned_graph(
    factory: async_sessionmaker[AsyncSession],
    *,
    lease_delta: timedelta = timedelta(seconds=30),
) -> tuple[Run, RunAttempt, RunWorker]:
    suffix = uuid.uuid4().hex
    async with factory() as session, session.begin():
        user = User(
            username=f"attempt-{suffix}",
            email=f"attempt-{suffix}@example.com",
            hashed_password="hash",
        )
        tenant = Tenant(name=f"Attempt {suffix}", slug=f"attempt-{suffix}")
        session.add_all([user, tenant])
        await session.flush()
        run_session = RunSession(tenant_id=tenant.id, created_by_user_id=user.id)
        worker = RunWorker(
            worker_type="chat",
            capacity=1,
            status="online",
            heartbeat_at=func.timezone("UTC", func.statement_timestamp()),
            started_at=func.timezone("UTC", func.statement_timestamp()),
            metadata_payload={},
        )
        session.add_all([run_session, worker])
        await session.flush()
        message = RunMessage(
            tenant_id=tenant.id,
            session_id=run_session.id,
            role="user",
            content="run",
            status="complete",
        )
        session.add(message)
        await session.flush()
        run = Run(
            tenant_id=tenant.id,
            session_id=run_session.id,
            created_by_user_id=user.id,
            run_type="chat",
            status="assigned",
            idempotency_key=f"attempt-{suffix}",
            request_hash=uuid.uuid4().hex,
            input_message_id=message.id,
            retry_count=0,
        )
        session.add(run)
        await session.flush()
        attempt = RunAttempt(
            run_id=run.id,
            attempt_no=1,
            status="assigned",
            worker_id=worker.id,
            lease_expires_at=func.timezone("UTC", func.statement_timestamp()) + lease_delta,
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
    return run, attempt, worker


def _service(factory: async_sessionmaker[AsyncSession]) -> AttemptService:
    return AttemptService(factory, lease_duration=timedelta(seconds=30))


@pytest.mark.asyncio
async def test_duplicate_claim_with_real_barrier_has_exactly_one_winner(
    attempt_factory: async_sessionmaker[AsyncSession],
) -> None:
    run, attempt, worker = await _assigned_graph(attempt_factory)
    barrier = TwoPartyBarrier()

    first, second = await asyncio.wait_for(
        asyncio.gather(
            BarrierAttemptService(attempt_factory, barrier).claim(attempt.id, worker.id),
            BarrierAttemptService(attempt_factory, barrier).claim(attempt.id, worker.id),
        ),
        timeout=2,
    )

    assert sorted(result.claimed for result in (first, second)) == [False, True]
    winner = first if first.claimed else second
    assert winner.assignment is not None
    assert winner.assignment.run_id == run.id
    assert (first.assignment is None) != (second.assignment is None)
    async with attempt_factory() as session:
        persisted = await session.get(RunAttempt, attempt.id)
        outbox = await session.scalar(select(RunOutbox).where(RunOutbox.attempt_id == attempt.id))
    assert persisted is not None and persisted.status == "running"
    assert persisted.claim_token == winner.assignment.claim_token
    assert outbox is not None and outbox.acknowledged_at is not None


@pytest.mark.asyncio
async def test_claim_rejects_wrong_worker_expired_lease_and_cancelled_run(
    attempt_factory: async_sessionmaker[AsyncSession],
) -> None:
    run, attempt, worker = await _assigned_graph(attempt_factory)
    service = _service(attempt_factory)

    assert not (await service.claim(attempt.id, uuid.uuid4())).claimed
    async with attempt_factory() as session, session.begin():
        await session.execute(
            update(RunAttempt)
            .where(RunAttempt.id == attempt.id)
            .values(lease_expires_at=func.timezone("UTC", func.statement_timestamp()))
        )
    assert not (await service.claim(attempt.id, worker.id)).claimed
    async with attempt_factory() as session, session.begin():
        await session.execute(
            update(RunAttempt)
            .where(RunAttempt.id == attempt.id)
            .values(
                lease_expires_at=func.timezone("UTC", func.statement_timestamp()) + timedelta(30)
            )
        )
        await session.execute(update(Run).where(Run.id == run.id).values(status="cancel_requested"))
    assert not (await service.claim(attempt.id, worker.id)).claimed


@pytest.mark.asyncio
async def test_renew_requires_matching_token_and_advances_from_database_statement_time(
    attempt_factory: async_sessionmaker[AsyncSession],
) -> None:
    _run, attempt, worker = await _assigned_graph(attempt_factory)
    service = _service(attempt_factory)
    claimed = await service.claim(attempt.id, worker.id)
    assert claimed.assignment is not None

    with pytest.raises(AttemptCommandRejected):
        await service.renew(attempt.id, worker.id, uuid.uuid4())
    renewed = await service.renew(attempt.id, worker.id, claimed.assignment.claim_token)

    assert renewed > claimed.assignment.lease_expires_at
    async with attempt_factory() as session:
        persisted = await session.get(RunAttempt, attempt.id)
    assert persisted is not None
    assert persisted.last_heartbeat_at is not None
    assert persisted.lease_expires_at == renewed


@pytest.mark.asyncio
async def test_complete_is_atomic_bounded_and_deep_copies_result(
    attempt_factory: async_sessionmaker[AsyncSession],
) -> None:
    run, attempt, worker = await _assigned_graph(attempt_factory)
    service = _service(attempt_factory)
    claimed = await service.claim(attempt.id, worker.id)
    assert claimed.assignment is not None
    result: dict[str, Any] = {"answer": {"items": [1]}}

    await service.complete_simulated(
        attempt.id,
        worker.id,
        claimed.assignment.claim_token,
        result,
    )
    cast(list[int], cast(Mapping[str, Any], result["answer"])["items"]).append(2)

    async with attempt_factory() as session:
        persisted_run = await session.get(Run, run.id)
        persisted_attempt = await session.get(RunAttempt, attempt.id)
        event = await session.scalar(
            select(RunEvent).where(
                RunEvent.run_id == run.id, RunEvent.event_type == "run.completed"
            )
        )
    assert persisted_run is not None and persisted_run.status == "completed"
    assert persisted_attempt is not None and persisted_attempt.status == "completed"
    assert persisted_run.finished_at == persisted_attempt.finished_at
    assert event is not None and event.payload["result"] == {"answer": {"items": [1]}}


@pytest.mark.asyncio
async def test_fail_bounds_error_and_keeps_run_attempt_event_consistent(
    attempt_factory: async_sessionmaker[AsyncSession],
) -> None:
    run, attempt, worker = await _assigned_graph(attempt_factory)
    service = _service(attempt_factory)
    claimed = await service.claim(attempt.id, worker.id)
    assert claimed.assignment is not None

    await service.fail(
        attempt.id,
        worker.id,
        claimed.assignment.claim_token,
        "simulated_error",
        "x" * 3000,
    )

    async with attempt_factory() as session:
        persisted_run = await session.get(Run, run.id)
        persisted_attempt = await session.get(RunAttempt, attempt.id)
        event = await session.scalar(
            select(RunEvent).where(RunEvent.run_id == run.id, RunEvent.event_type == "run.failed")
        )
    assert persisted_run is not None and persisted_attempt is not None and event is not None
    assert persisted_run.status == persisted_attempt.status == "failed"
    assert persisted_run.error_code == persisted_attempt.error_code == "simulated_error"
    assert len(cast(str, persisted_run.error_message)) == 2000
    assert event.payload["error_message"] == persisted_run.error_message


@pytest.mark.asyncio
async def test_zombie_or_expired_token_cannot_complete_fail_or_acknowledge_cancel(
    attempt_factory: async_sessionmaker[AsyncSession],
) -> None:
    run, attempt, worker = await _assigned_graph(attempt_factory)
    service = _service(attempt_factory)
    claimed = await service.claim(attempt.id, worker.id)
    assert claimed.assignment is not None
    async with attempt_factory() as session, session.begin():
        await session.execute(
            update(RunAttempt)
            .where(RunAttempt.id == attempt.id)
            .values(lease_expires_at=func.timezone("UTC", func.statement_timestamp()))
        )
        await session.execute(update(Run).where(Run.id == run.id).values(status="cancel_requested"))

    commands = (
        service.complete_simulated(
            attempt.id, worker.id, claimed.assignment.claim_token, {"answer": "late"}
        ),
        service.fail(attempt.id, worker.id, claimed.assignment.claim_token, "late", "late"),
        service.acknowledge_cancel(attempt.id, worker.id, claimed.assignment.claim_token),
    )
    for command in commands:
        with pytest.raises(AttemptCommandRejected):
            await command


@pytest.mark.asyncio
async def test_acknowledge_cancel_atomically_finishes_and_acknowledges_outbox(
    attempt_factory: async_sessionmaker[AsyncSession],
) -> None:
    run, attempt, worker = await _assigned_graph(attempt_factory)
    service = _service(attempt_factory)
    claimed = await service.claim(attempt.id, worker.id)
    assert claimed.assignment is not None
    async with attempt_factory() as session, session.begin():
        await session.execute(update(Run).where(Run.id == run.id).values(status="cancel_requested"))
        session.add(
            RunOutbox(
                event_type="attempt.cancel",
                tenant_id=run.tenant_id,
                run_id=run.id,
                attempt_id=attempt.id,
                worker_id=worker.id,
                payload={},
                dedupe_key=f"attempt.cancel:{run.id}",
            )
        )

    await service.acknowledge_cancel(attempt.id, worker.id, claimed.assignment.claim_token)

    async with attempt_factory() as session:
        persisted_run = await session.get(Run, run.id)
        persisted_attempt = await session.get(RunAttempt, attempt.id)
        cancel = await session.scalar(
            select(RunOutbox).where(RunOutbox.event_type == "attempt.cancel")
        )
    assert persisted_run is not None and persisted_run.status == "cancelled"
    assert persisted_attempt is not None and persisted_attempt.status == "cancelled"
    assert cancel is not None and cancel.acknowledged_at is not None
