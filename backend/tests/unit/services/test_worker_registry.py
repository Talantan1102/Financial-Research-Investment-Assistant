from __future__ import annotations

import asyncio
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any, cast

import pytest
import pytest_asyncio
from app.models.run import Run, RunAttempt, RunMessage, RunSession
from app.models.run_scheduling import RunWorker
from app.models.tenant import Tenant
from app.models.user import User
from app.services.worker_registry import WorkerRegistry, load_schedulable_workers
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture
async def worker_registry(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> WorkerRegistry:
    return WorkerRegistry(async_session_factory, heartbeat_ttl=timedelta(seconds=30))


@pytest_asyncio.fixture(autouse=True)
async def cleanup_created_workers(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[None]:
    async with async_session_factory() as session:
        existing_ids = set((await session.scalars(select(RunWorker.id))).all())
        existing_tenant_ids = set((await session.scalars(select(Tenant.id))).all())
        existing_user_ids = set((await session.scalars(select(User.id))).all())
    yield
    async with async_session_factory() as session, session.begin():
        created_ids = set((await session.scalars(select(RunWorker.id))).all()) - existing_ids
        if created_ids:
            await session.execute(delete(RunAttempt).where(RunAttempt.worker_id.in_(created_ids)))
            await session.execute(delete(RunWorker).where(RunWorker.id.in_(created_ids)))
        created_tenant_ids = (
            set((await session.scalars(select(Tenant.id))).all()) - existing_tenant_ids
        )
        if created_tenant_ids:
            await session.execute(delete(Tenant).where(Tenant.id.in_(created_tenant_ids)))
        created_user_ids = set((await session.scalars(select(User.id))).all()) - existing_user_ids
        if created_user_ids:
            await session.execute(delete(User).where(User.id.in_(created_user_ids)))


async def _database_utc_now(session: AsyncSession) -> datetime:
    value = await session.scalar(select(func.timezone("UTC", func.current_timestamp())))
    assert isinstance(value, datetime)
    return value


@pytest.mark.asyncio
async def test_register_creates_online_chat_worker_with_metadata_and_new_uuid(
    worker_registry: WorkerRegistry,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first = await worker_registry.register(capacity=2, metadata={"pid": 123, "version": "v2"})
    second = await worker_registry.register(capacity=2, metadata={"pid": 123})

    assert first.id != second.id
    assert first.worker_type == "chat"
    assert first.capacity == 2
    assert first.status == "online"
    assert first.active_attempts == 0
    assert first.metadata == {"pid": 123, "version": "v2"}
    async with async_session_factory() as session:
        persisted = await session.get(RunWorker, first.id)
        database_now = await _database_utc_now(session)
    assert persisted is not None
    assert persisted.metadata_payload == first.metadata
    assert abs((database_now - first.heartbeat_at).total_seconds()) < 5


@pytest.mark.asyncio
async def test_register_rejects_non_positive_capacity(worker_registry: WorkerRegistry) -> None:
    for capacity in (0, -1):
        with pytest.raises(ValueError, match="capacity must be positive"):
            await worker_registry.register(capacity=capacity, metadata={})


@pytest.mark.asyncio
async def test_heartbeat_uses_database_utc_and_refreshes_liveness(
    worker_registry: WorkerRegistry,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with async_session_factory() as session:
        await session.execute(text("SET TIME ZONE 'Asia/Shanghai'"))
        await session.commit()
    worker = await worker_registry.register(capacity=1, metadata={})
    async with async_session_factory() as session, session.begin():
        await session.execute(
            update(RunWorker)
            .where(RunWorker.id == worker.id)
            .values(
                heartbeat_at=func.timezone("UTC", func.current_timestamp()) - timedelta(hours=1)
            )
        )

    await worker_registry.heartbeat(worker.id)
    refreshed = await worker_registry.get(worker.id)

    async with async_session_factory() as session:
        assert await session.scalar(text("SHOW TIME ZONE")) == "Asia/Shanghai"
        database_now = await _database_utc_now(session)
    assert abs((database_now - refreshed.heartbeat_at).total_seconds()) < 5


@pytest.mark.asyncio
async def test_drain_and_offline_workers_are_not_schedulable(
    worker_registry: WorkerRegistry,
) -> None:
    draining = await worker_registry.register(capacity=1, metadata={"name": "draining"})
    offline = await worker_registry.register(capacity=1, metadata={"name": "offline"})

    await worker_registry.drain(draining.id)
    await worker_registry.mark_offline(offline.id)

    assert (await worker_registry.get(draining.id)).status == "draining"
    assert (await worker_registry.get(offline.id)).status == "offline"
    schedulable_ids = {item.id for item in await worker_registry.list_schedulable()}
    assert draining.id not in schedulable_ids
    assert offline.id not in schedulable_ids


@pytest.mark.asyncio
async def test_stale_heartbeat_and_full_worker_are_not_schedulable(
    worker_registry: WorkerRegistry,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    stale = await worker_registry.register(capacity=2, metadata={"name": "stale"})
    full = await worker_registry.register(capacity=1, metadata={"name": "full"})
    await _add_attempts(
        async_session_factory,
        worker_id=full.id,
        attempts=(("assigned", timedelta(minutes=1)),),
    )
    async with async_session_factory() as session, session.begin():
        await session.execute(
            update(RunWorker)
            .where(RunWorker.id == stale.id)
            .values(
                heartbeat_at=func.timezone("UTC", func.current_timestamp()) - timedelta(minutes=1)
            )
        )

    schedulable_ids = {item.id for item in await worker_registry.list_schedulable()}
    assert stale.id not in schedulable_ids
    assert full.id not in schedulable_ids


@pytest.mark.asyncio
async def test_active_load_is_derived_only_from_live_assigned_and_running_attempts(
    worker_registry: WorkerRegistry,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    worker = await worker_registry.register(capacity=5, metadata={})
    await _add_attempts(
        async_session_factory,
        worker_id=worker.id,
        attempts=(
            ("assigned", timedelta(minutes=1)),
            ("running", timedelta(minutes=1)),
            ("completed", timedelta(minutes=1)),
            ("assigned", timedelta(seconds=-1)),
            ("running", None),
        ),
    )

    snapshot = await worker_registry.get(worker.id)
    schedulable = await worker_registry.list_schedulable()

    assert snapshot.active_attempts == 2
    matching = [item for item in schedulable if item.id == worker.id]
    assert [(item.id, item.active_attempts) for item in matching] == [(worker.id, 2)]


@pytest.mark.asyncio
async def test_transaction_bound_helper_does_not_commit_callers_transaction(
    worker_registry: WorkerRegistry,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    worker = await worker_registry.register(capacity=1, metadata={})

    async with async_session_factory() as session, session.begin():
        row = await session.get(RunWorker, worker.id, with_for_update=True)
        assert row is not None
        cast(Any, row).status = "draining"
        schedulable_ids = {
            item.id
            for item in await load_schedulable_workers(session, heartbeat_ttl=timedelta(seconds=30))
        }
        assert worker.id not in schedulable_ids
        await session.rollback()

    assert (await worker_registry.get(worker.id)).status == "online"


async def _add_attempts(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    worker_id: uuid.UUID,
    attempts: tuple[tuple[str, timedelta | None], ...],
) -> None:
    suffix = uuid.uuid4().hex
    async with session_factory() as session, session.begin():
        user = User(
            username=f"worker-registry-{suffix}",
            email=f"worker-registry-{suffix}@example.com",
            hashed_password="test-password-hash",
        )
        tenant = Tenant(name="Worker registry tenant", slug=f"worker-registry-{suffix}")
        session.add_all([user, tenant])
        await session.flush()
        run_session = RunSession(tenant_id=tenant.id, created_by_user_id=user.id)
        session.add(run_session)
        await session.flush()
        message = RunMessage(
            tenant_id=tenant.id,
            session_id=run_session.id,
            role="user",
            content="test",
            status="completed",
        )
        session.add(message)
        await session.flush()
        run = Run(
            tenant_id=tenant.id,
            session_id=run_session.id,
            created_by_user_id=user.id,
            status="assigned",
            idempotency_key=f"worker-registry-{suffix}",
            request_hash="0" * 64,
            input_message_id=message.id,
        )
        session.add(run)
        await session.flush()
        database_now = await _database_utc_now(session)
        session.add_all(
            [
                RunAttempt(
                    run_id=run.id,
                    attempt_no=attempt_no,
                    status=status,
                    worker_id=worker_id,
                    lease_expires_at=(database_now + lease_delta if lease_delta else None),
                )
                for attempt_no, (status, lease_delta) in enumerate(attempts, start=1)
            ]
        )
