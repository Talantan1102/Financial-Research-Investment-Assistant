from __future__ import annotations

import asyncio
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import cast

import pytest
from app.models.run_scheduling import RunOutbox
from app.processes.run_dispatcher import RunDispatcher
from app.run_control.redis_transport import RedisTransport
from app.run_control.types import OutboxType
from app.services.run_outbox import RunOutboxService
from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.unit.services.test_run_outbox import _outbox
from tests.unit.services.test_run_outbox import outbox_factory as outbox_factory


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture
async def real_redis(redis_url: str) -> AsyncIterator[Redis]:
    redis = Redis.from_url(redis_url, decode_responses=False)
    await redis.flushdb()
    try:
        yield redis
    finally:
        await redis.aclose()


class CrashAfterXaddService(RunOutboxService):
    async def mark_delivered(self, item_id: uuid.UUID) -> None:
        del item_id
        raise RuntimeError("simulated process crash after XADD")


async def test_dispatches_all_event_types_to_true_redis(
    outbox_factory: async_sessionmaker[AsyncSession],
    real_redis: Redis,
) -> None:
    assignment_id = await _outbox(outbox_factory)
    cancel_id = await _outbox(outbox_factory, OutboxType.ATTEMPT_CANCEL)
    wake_id = await _outbox(outbox_factory, OutboxType.SCHEDULE_WAKE)
    service = RunOutboxService(outbox_factory)

    delivered = await RunDispatcher(service, RedisTransport(real_redis)).dispatch_once()

    assert delivered == 3
    async with outbox_factory() as session:
        rows = (
            await session.scalars(
                select(RunOutbox).where(RunOutbox.id.in_([assignment_id, cancel_id, wake_id]))
            )
        ).all()
        assert all(row.delivered_at is not None for row in rows)
    assert await real_redis.xlen("run:scheduler:wake") == 1
    assignment = next(row for row in rows if row.id == assignment_id)
    assert await real_redis.xlen(f"run:worker:{assignment.worker_id}:assignments") == 1
    cancel = next(row for row in rows if row.id == cancel_id)
    assert await real_redis.xlen(f"run:attempt:{cancel.attempt_id}:control") == 1


async def test_xadd_success_then_db_crash_is_safely_redelivered(
    outbox_factory: async_sessionmaker[AsyncSession],
    real_redis: Redis,
) -> None:
    item_id = await _outbox(outbox_factory)
    crash_service = CrashAfterXaddService(outbox_factory, lock_timeout=timedelta(milliseconds=1))
    with pytest.raises(RuntimeError, match="after XADD"):
        await RunDispatcher(crash_service, RedisTransport(real_redis)).dispatch_once()

    async with outbox_factory() as session:
        row = await session.get(RunOutbox, item_id)
        assert row is not None and row.delivered_at is None
        key = f"run:worker:{row.worker_id}:assignments"
        assert await real_redis.xlen(key) == 1
    async with outbox_factory() as session, session.begin():
        await session.execute(
            update(RunOutbox)
            .where(RunOutbox.id == item_id)
            .values(
                claimed_at=func.timezone("UTC", func.statement_timestamp()) - timedelta(seconds=1)
            )
        )
    normal = RunOutboxService(outbox_factory, lock_timeout=timedelta(milliseconds=1))
    assert await RunDispatcher(normal, RedisTransport(real_redis)).dispatch_once() == 1
    assert await real_redis.xlen(key) == 2


class BrokenRedis:
    async def xadd(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        raise ConnectionError("redis://user:password@host Authorization: Bearer token")


async def test_redis_failure_keeps_postgres_outbox_for_retry(
    outbox_factory: async_sessionmaker[AsyncSession],
) -> None:
    item_id = await _outbox(outbox_factory)
    service = RunOutboxService(outbox_factory)
    dispatcher = RunDispatcher(service, RedisTransport(cast(Redis, BrokenRedis())))

    assert await dispatcher.dispatch_once() == 0

    async with outbox_factory() as session:
        row = await session.get(RunOutbox, item_id)
        assert row is not None
        assert row.delivered_at is None and row.next_attempt_at is not None
        assert "password" not in row.last_error.lower()
        assert "token" not in row.last_error.lower()
