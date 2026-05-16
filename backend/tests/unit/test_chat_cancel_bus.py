"""ChatCancelBus L0 unit — Redis pub/sub publish + subscribe 封装。

测试覆盖:
- publish_cancel 写入 Redis pub/sub channel
- subscribe_cancel 接到 publish 的 signal
- Multi-listener fan-out:同 channel 多个 subscriber 都收到
- 不同 task_id 不互串
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid

import pytest
from app.services.chat_cancel_bus import ChatCancelBus
from fakeredis.aioredis import FakeRedis


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis(decode_responses=False)


async def test_publish_then_subscribe_delivers_signal(fake_redis: FakeRedis) -> None:
    bus = ChatCancelBus(redis=fake_redis)
    tid = uuid.uuid4()

    received: list[bool] = []
    flag = asyncio.Event()

    async def listener() -> None:
        async for _ in bus.subscribe_cancel(tid):
            received.append(True)
            flag.set()
            return

    listener_task = asyncio.create_task(listener())
    # Give listener a moment to subscribe
    await asyncio.sleep(0.05)
    await bus.publish_cancel(tid)
    await asyncio.wait_for(flag.wait(), timeout=2.0)
    await listener_task
    assert received == [True]


async def test_publish_without_subscriber_returns_zero(fake_redis: FakeRedis) -> None:
    """publish 时没人 listen — 应该 return 0 而不抛异常。"""
    bus = ChatCancelBus(redis=fake_redis)
    tid = uuid.uuid4()
    receivers = await bus.publish_cancel(tid)
    assert receivers == 0


async def test_two_listeners_both_receive(fake_redis: FakeRedis) -> None:
    bus = ChatCancelBus(redis=fake_redis)
    tid = uuid.uuid4()
    flags = [asyncio.Event(), asyncio.Event()]

    async def listener(idx: int) -> None:
        async for _ in bus.subscribe_cancel(tid):
            flags[idx].set()
            return

    listener_tasks = [asyncio.create_task(listener(i)) for i in (0, 1)]
    await asyncio.sleep(0.05)
    await bus.publish_cancel(tid)
    for f in flags:
        await asyncio.wait_for(f.wait(), timeout=2.0)
    for t in listener_tasks:
        await t


async def test_different_task_ids_isolated(fake_redis: FakeRedis) -> None:
    bus = ChatCancelBus(redis=fake_redis)
    tid1 = uuid.uuid4()
    tid2 = uuid.uuid4()
    got_tid1 = asyncio.Event()
    got_tid2 = asyncio.Event()

    async def listener_for(tid: uuid.UUID, flag: asyncio.Event) -> None:
        async for _ in bus.subscribe_cancel(tid):
            flag.set()
            return

    t1 = asyncio.create_task(listener_for(tid1, got_tid1))
    t2 = asyncio.create_task(listener_for(tid2, got_tid2))
    await asyncio.sleep(0.05)
    await bus.publish_cancel(tid1)
    await asyncio.wait_for(got_tid1.wait(), timeout=2.0)
    # tid2 should NOT have been triggered
    assert not got_tid2.is_set()
    # cleanup
    t2.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await t2
    await t1
