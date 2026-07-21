from __future__ import annotations

import asyncio
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from types import MappingProxyType
from typing import cast

import pytest
import pytest_asyncio
from app.core.database import Base
from app.models.run import Run, RunAttempt, RunMessage, RunSession
from app.models.run_scheduling import RunOutbox, RunWorker
from app.models.tenant import Tenant
from app.models.user import User
from app.run_control.types import OutboxType
from app.services.run_outbox import RunOutboxService
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture
async def outbox_factory(
    pg_test_container: dict[str, object],
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = str(pg_test_container["url"]).replace("postgresql://", "postgresql+psycopg://", 1)
    schema = f"run_outbox_{uuid.uuid4().hex}"
    admin = create_async_engine(url)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(url, connect_args={"options": f"-c search_path={schema}"})
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def _outbox(
    factory: async_sessionmaker[AsyncSession],
    event_type: OutboxType = OutboxType.ATTEMPT_ASSIGNED,
) -> uuid.UUID:
    suffix = uuid.uuid4().hex
    async with factory() as session, session.begin():
        user = User(
            username=f"outbox-{suffix}",
            email=f"outbox-{suffix}@example.com",
            hashed_password="hash",
        )
        tenant = Tenant(name=f"Outbox {suffix}", slug=f"outbox-{suffix}")
        session.add_all([user, tenant])
        await session.flush()
        run_session = RunSession(tenant_id=tenant.id, created_by_user_id=user.id)
        session.add(run_session)
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
            status="assigned" if event_type is not OutboxType.SCHEDULE_WAKE else "queued",
            idempotency_key=f"outbox-{suffix}",
            request_hash=uuid.uuid4().hex,
            input_message_id=message.id,
            revision_seq=1,
            retry_count=0,
        )
        session.add(run)
        await session.flush()
        attempt = None
        worker = None
        if event_type is not OutboxType.SCHEDULE_WAKE:
            worker = RunWorker(
                worker_type="chat",
                capacity=1,
                status="online",
                heartbeat_at=func.timezone("UTC", func.statement_timestamp()),
                started_at=func.timezone("UTC", func.statement_timestamp()),
                metadata_payload={},
            )
            session.add(worker)
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
        row = RunOutbox(
            event_type=event_type.value,
            tenant_id=tenant.id,
            run_id=run.id,
            attempt_id=attempt.id if attempt else None,
            worker_id=worker.id if worker else None,
            payload={"nested": {"values": [1, 2]}},
            dedupe_key=f"test:{suffix}",
        )
        session.add(row)
        await session.flush()
        return cast(uuid.UUID, row.id)


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


class BarrierOutboxService(RunOutboxService):
    def __init__(self, factory: async_sessionmaker[AsyncSession], barrier: TwoPartyBarrier) -> None:
        super().__init__(factory)
        self._barrier = barrier

    async def _before_claim_selection(self) -> None:
        await self._barrier.wait()


async def test_concurrent_batch_claim_uses_skip_locked_without_duplicates(
    outbox_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = {await _outbox(outbox_factory), await _outbox(outbox_factory)}
    barrier = TwoPartyBarrier()
    first, second = await asyncio.wait_for(
        asyncio.gather(
            BarrierOutboxService(outbox_factory, barrier).claim_batch(uuid.uuid4(), 1),
            BarrierOutboxService(outbox_factory, barrier).claim_batch(uuid.uuid4(), 1),
        ),
        timeout=2,
    )
    claimed = {item.id for item in (*first, *second)}
    assert claimed == ids
    assert len(first) == len(second) == 1


async def test_claim_projection_is_deeply_immutable_and_lock_expires(
    outbox_factory: async_sessionmaker[AsyncSession],
) -> None:
    item_id = await _outbox(outbox_factory)
    service = RunOutboxService(outbox_factory, lock_timeout=timedelta(seconds=30))
    item = (await service.claim_batch(uuid.uuid4(), 1))[0]
    assert isinstance(item.payload, MappingProxyType)
    with pytest.raises(TypeError):
        item.payload["x"] = 1  # type: ignore[index]
    with pytest.raises(TypeError):
        item.payload["nested"]["x"] = 1
    assert await service.claim_batch(uuid.uuid4(), 1) == ()
    async with outbox_factory() as session, session.begin():
        await session.execute(
            update(RunOutbox)
            .where(RunOutbox.id == item_id)
            .values(
                claimed_at=func.timezone("UTC", func.statement_timestamp()) - timedelta(seconds=31)
            )
        )
    assert (await service.claim_batch(uuid.uuid4(), 1))[0].id == item_id


async def test_failed_delivery_redacts_credentials_and_caps_exponential_backoff(
    outbox_factory: async_sessionmaker[AsyncSession],
) -> None:
    item_id = await _outbox(outbox_factory)
    service = RunOutboxService(
        outbox_factory,
        retry_base=timedelta(seconds=2),
        retry_cap=timedelta(seconds=5),
    )
    unsafe_errors = (
        "Authorization: Bearer bearer-secret Cookie: session=cookie-secret",
        "AWS_ACCESS_KEY_ID=AKIAEXAMPLE AWS_SECRET_ACCESS_KEY=aws-secret",
        "redis://:urlsecret@cache/1?password=query-secret",
        "x" * 1_000_000,
    )
    owner = uuid.uuid4()
    for expected_delay, unsafe_error in zip((2, 4, 5, 5), unsafe_errors, strict=True):
        item = (await service.claim_batch(owner, 1))[0]
        await service.mark_failed(
            item_id,
            owner,
            item.delivery_attempts,
            unsafe_error,
        )
        async with outbox_factory() as session:
            row = await session.get(RunOutbox, item_id)
            assert row is not None and row.next_attempt_at is not None
            delay = row.next_attempt_at - row.claimed_at if row.claimed_at else None
            assert delay is None  # claim ownership is cleared on failure
            assert row.last_error == "delivery_failed"
            now = await session.scalar(select(func.timezone("UTC", func.statement_timestamp())))
            assert (
                expected_delay - 0.25
                <= (row.next_attempt_at - now).total_seconds()
                <= expected_delay
            )
        async with outbox_factory() as session, session.begin():
            await session.execute(
                update(RunOutbox)
                .where(RunOutbox.id == item_id)
                .values(next_attempt_at=func.timezone("UTC", func.statement_timestamp()))
            )


def test_retry_delay_caps_before_large_exponent_is_constructed(
    outbox_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = RunOutboxService(
        outbox_factory,
        retry_base=timedelta(seconds=2),
        retry_cap=timedelta(seconds=5),
    )
    assert [service._retry_delay(value) for value in (48, 64, 10_000)] == [
        timedelta(seconds=5),
        timedelta(seconds=5),
        timedelta(seconds=5),
    ]


async def test_assignment_redelivers_until_acknowledged_but_schedule_wake_is_one_shot(
    outbox_factory: async_sessionmaker[AsyncSession],
) -> None:
    assignment_id = await _outbox(outbox_factory)
    wake_id = await _outbox(outbox_factory, OutboxType.SCHEDULE_WAKE)
    service = RunOutboxService(outbox_factory, retry_base=timedelta(seconds=1))

    owner = uuid.uuid4()
    claimed = await service.claim_batch(owner, 10)
    by_id = {item.id: item for item in claimed}
    await service.mark_delivered(assignment_id, owner, by_id[assignment_id].delivery_attempts)
    await service.mark_delivered(wake_id, owner, by_id[wake_id].delivery_attempts)
    assert assignment_id in by_id and wake_id in by_id
    async with outbox_factory() as session, session.begin():
        await session.execute(
            update(RunOutbox)
            .where(RunOutbox.id == assignment_id)
            .values(next_attempt_at=func.timezone("UTC", func.statement_timestamp()))
        )
    assert [item.id for item in await service.claim_batch(uuid.uuid4(), 10)] == [assignment_id]
    async with outbox_factory() as session, session.begin():
        await session.execute(
            update(RunOutbox)
            .where(RunOutbox.id == assignment_id)
            .values(
                acknowledged_at=func.timezone("UTC", func.statement_timestamp()),
                claimed_at=None,
                claimed_by=None,
            )
        )
    assert await service.claim_batch(uuid.uuid4(), 10) == ()
    async with outbox_factory() as session:
        wake = await session.get(RunOutbox, wake_id)
        assert wake is not None and wake.acknowledged_at == wake.delivered_at


async def test_stale_owner_and_generation_cannot_overwrite_reclaimed_delivery(
    outbox_factory: async_sessionmaker[AsyncSession],
) -> None:
    item_id = await _outbox(outbox_factory)
    service = RunOutboxService(outbox_factory, lock_timeout=timedelta(milliseconds=1))
    owner_a, owner_b = uuid.uuid4(), uuid.uuid4()
    claim_a = (await service.claim_batch(owner_a, 1))[0]
    async with outbox_factory() as session, session.begin():
        await session.execute(
            update(RunOutbox)
            .where(RunOutbox.id == item_id)
            .values(
                claimed_at=func.timezone("UTC", func.statement_timestamp()) - timedelta(seconds=1)
            )
        )
    claim_b = (await service.claim_batch(owner_b, 1))[0]

    with pytest.raises(RuntimeError, match="claim"):
        await service.mark_delivered(item_id, owner_a, claim_a.delivery_attempts)
    async with outbox_factory() as session:
        row = await session.get(RunOutbox, item_id)
        assert row is not None
        assert row.claimed_by == str(owner_b)
        assert row.delivery_attempts == claim_b.delivery_attempts
        assert row.delivered_at is None
    await service.mark_delivered(item_id, owner_b, claim_b.delivery_attempts)


async def test_same_dispatcher_aba_is_fenced_by_delivery_generation(
    outbox_factory: async_sessionmaker[AsyncSession],
) -> None:
    item_id = await _outbox(outbox_factory)
    service = RunOutboxService(outbox_factory, lock_timeout=timedelta(milliseconds=1))
    owner = uuid.uuid4()
    first = (await service.claim_batch(owner, 1))[0]
    async with outbox_factory() as session, session.begin():
        await session.execute(
            update(RunOutbox)
            .where(RunOutbox.id == item_id)
            .values(
                claimed_at=func.timezone("UTC", func.statement_timestamp()) - timedelta(seconds=1)
            )
        )
    second = (await service.claim_batch(owner, 1))[0]
    assert second.delivery_attempts == first.delivery_attempts + 1

    with pytest.raises(RuntimeError, match="claim"):
        await service.mark_failed(
            item_id,
            owner,
            first.delivery_attempts,
            "redis_connection_error",
        )
    await service.mark_failed(
        item_id,
        owner,
        second.delivery_attempts,
        "redis_connection_error",
    )
    async with outbox_factory() as session:
        row = await session.get(RunOutbox, item_id)
        assert row is not None and row.last_error == "redis_connection_error"


async def test_never_claimed_item_rejects_delivery_mutation(
    outbox_factory: async_sessionmaker[AsyncSession],
) -> None:
    item_id = await _outbox(outbox_factory)
    service = RunOutboxService(outbox_factory)
    with pytest.raises(RuntimeError, match="claim"):
        await service.mark_delivered(item_id, uuid.uuid4(), 0)
    async with outbox_factory() as session:
        row = await session.get(RunOutbox, item_id)
        assert row is not None
        assert row.claimed_by is None and row.delivered_at is None
