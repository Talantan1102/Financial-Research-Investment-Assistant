from __future__ import annotations

import asyncio
import json
import sys
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import cast

import pytest
from app.models.run_scheduling import RunOutbox
from app.processes.run_dispatcher import RunDispatcher
from app.run_control.redis_transport import RedisTransport
from app.run_control.types import OutboxType
from app.services.run_outbox import RunOutboxService
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.unit.services.test_run_outbox import _outbox
from tests.unit.services.test_run_outbox import outbox_factory as outbox_factory


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@dataclass
class RedisTestScope:
    redis: Redis
    sentinel_key: str
    unique_keys: set[str] = field(default_factory=set)
    shared_outbox_ids: set[uuid.UUID] = field(default_factory=set)


@pytest.fixture
async def shared_redis_sentinel(redis_url: str) -> AsyncIterator[str]:
    redis = Redis.from_url(redis_url, decode_responses=False)
    sentinel_key = f"task5:preexisting:{uuid.uuid4()}"
    await redis.set(sentinel_key, b"preserve")
    try:
        yield sentinel_key
        assert await redis.get(sentinel_key) == b"preserve"
    finally:
        await redis.delete(sentinel_key)
        await redis.aclose()


@pytest.fixture
async def real_redis(
    redis_url: str,
    shared_redis_sentinel: str,
) -> AsyncIterator[RedisTestScope]:
    redis = Redis.from_url(redis_url, decode_responses=False)
    scope = RedisTestScope(redis=redis, sentinel_key=shared_redis_sentinel)
    try:
        yield scope
    finally:
        assert await redis.get(shared_redis_sentinel) == b"preserve"
        for key in scope.unique_keys:
            await redis.delete(key)
        wake_entries = await redis.xrange("run:scheduler:wake")
        owned_entry_ids = []
        for entry_id, fields in wake_entries:
            envelope = json.loads(fields[b"data"])
            if uuid.UUID(envelope["outbox_id"]) in scope.shared_outbox_ids:
                owned_entry_ids.append(entry_id)
        if owned_entry_ids:
            await redis.xdel("run:scheduler:wake", *owned_entry_ids)
        await redis.aclose()


class CrashAfterXaddService(RunOutboxService):
    async def mark_delivered(
        self,
        item_id: uuid.UUID,
        dispatcher_id: uuid.UUID,
        delivery_attempts: int,
    ) -> None:
        del item_id, dispatcher_id, delivery_attempts
        raise RuntimeError("simulated process crash after XADD")


async def test_fixture_preserves_unrelated_redis_sentinel(real_redis: RedisTestScope) -> None:
    assert await real_redis.redis.get(real_redis.sentinel_key) == b"preserve"


async def test_dispatches_all_event_types_to_true_redis(
    outbox_factory: async_sessionmaker[AsyncSession],
    real_redis: RedisTestScope,
) -> None:
    assignment_id = await _outbox(outbox_factory)
    cancel_id = await _outbox(outbox_factory, OutboxType.ATTEMPT_CANCEL)
    wake_id = await _outbox(outbox_factory, OutboxType.SCHEDULE_WAKE)
    service = RunOutboxService(outbox_factory)
    async with outbox_factory() as session:
        seeded_rows = (
            await session.scalars(
                select(RunOutbox).where(RunOutbox.id.in_([assignment_id, cancel_id]))
            )
        ).all()
    for row in seeded_rows:
        if row.event_type == OutboxType.ATTEMPT_ASSIGNED.value:
            real_redis.unique_keys.add(f"run:worker:{row.worker_id}:assignments")
        else:
            real_redis.unique_keys.add(f"run:attempt:{row.attempt_id}:control")
    real_redis.shared_outbox_ids.add(wake_id)

    delivered = await RunDispatcher(service, RedisTransport(real_redis.redis)).dispatch_once()

    assert delivered == 3
    async with outbox_factory() as session:
        rows = (
            await session.scalars(
                select(RunOutbox).where(RunOutbox.id.in_([assignment_id, cancel_id, wake_id]))
            )
        ).all()
        assert all(row.delivered_at is not None for row in rows)
    wake_entries = await real_redis.redis.xrange("run:scheduler:wake")
    assert any(
        json.loads(fields[b"data"])["outbox_id"] == str(wake_id) for _, fields in wake_entries
    )
    assignment = next(row for row in rows if row.id == assignment_id)
    assert await real_redis.redis.xlen(f"run:worker:{assignment.worker_id}:assignments") == 1
    cancel = next(row for row in rows if row.id == cancel_id)
    assert await real_redis.redis.xlen(f"run:attempt:{cancel.attempt_id}:control") == 1


async def test_xadd_success_then_db_crash_is_safely_redelivered(
    outbox_factory: async_sessionmaker[AsyncSession],
    real_redis: RedisTestScope,
) -> None:
    item_id = await _outbox(outbox_factory)
    async with outbox_factory() as session:
        seeded = await session.get(RunOutbox, item_id)
        assert seeded is not None
        key = f"run:worker:{seeded.worker_id}:assignments"
        real_redis.unique_keys.add(key)
    crash_service = CrashAfterXaddService(outbox_factory, lock_timeout=timedelta(milliseconds=1))
    with pytest.raises(RuntimeError, match="after XADD"):
        await RunDispatcher(crash_service, RedisTransport(real_redis.redis)).dispatch_once()

    async with outbox_factory() as session:
        row = await session.get(RunOutbox, item_id)
        assert row is not None and row.delivered_at is None
        assert await real_redis.redis.xlen(key) == 1
    async with outbox_factory() as session, session.begin():
        await session.execute(
            update(RunOutbox)
            .where(RunOutbox.id == item_id)
            .values(
                claimed_at=func.timezone("UTC", func.statement_timestamp()) - timedelta(seconds=1)
            )
        )
    normal = RunOutboxService(outbox_factory, lock_timeout=timedelta(milliseconds=1))
    assert await RunDispatcher(normal, RedisTransport(real_redis.redis)).dispatch_once() == 1
    assert await real_redis.redis.xlen(key) == 2


class BrokenRedis:
    def __init__(self) -> None:
        self.called = asyncio.Event()

    async def xadd(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        self.called.set()
        raise RedisConnectionError("redis://user:password@host Authorization: Bearer token")


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (RedisConnectionError("secret"), "redis_connection_error"),
        (RedisTimeoutError("secret"), "redis_timeout"),
    ],
)
def test_dispatcher_maps_real_redis_exception_classes_to_safe_codes(
    error: Exception,
    expected_code: str,
) -> None:
    assert RunDispatcher._delivery_error_code(error) == expected_code


async def test_redis_failure_keeps_postgres_outbox_for_retry(
    outbox_factory: async_sessionmaker[AsyncSession],
) -> None:
    item_id = await _outbox(outbox_factory)
    async with outbox_factory() as session, session.begin():
        await session.execute(
            update(RunOutbox).where(RunOutbox.id == item_id).values(delivery_attempts=9_999)
        )
    service = RunOutboxService(
        outbox_factory,
        retry_base=timedelta(seconds=2),
        retry_cap=timedelta(seconds=5),
    )
    broken_redis = BrokenRedis()
    dispatcher = RunDispatcher(
        service,
        RedisTransport(cast(Redis, broken_redis)),
        poll_interval=0.01,
    )

    loop_task = asyncio.create_task(dispatcher.run_forever())
    await asyncio.wait_for(broken_redis.called.wait(), timeout=1)
    dispatcher.request_shutdown()
    await asyncio.wait_for(loop_task, timeout=1)

    async with outbox_factory() as session:
        row = await session.get(RunOutbox, item_id)
        assert row is not None
        assert row.delivered_at is None and row.next_attempt_at is not None
        assert row.delivery_attempts == 10_000
        assert row.last_error == "redis_connection_error"
