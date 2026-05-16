"""ChatEventBus L0 unit — Redis Streams XADD / XREAD / TTL 封装。

测试策略:fakeredis-py 跑 async Redis(无外部依赖,L0 单元测试要求快+ isolated)。
覆盖 7 个用例:
- xadd_event 返回 Redis stream entry id (millisecond-seq 形式)
- xread_blocking 从 "0" 读到所有 entries
- xread_blocking 传 last_id 只读之后的新 entries
- 空 stream 上 block 超时返空列表
- set_ttl 让 stream 24h 过期(PTTL 检查)
- 大 payload (>1KB) 也能 roundtrip
- 不同 (sid, tid) 的 stream 互相隔离
"""

from __future__ import annotations

import uuid

import pytest
from app.services.chat_event_bus import ChatEventBus
from fakeredis.aioredis import FakeRedis


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis(decode_responses=False)


@pytest.fixture
def bus(fake_redis: FakeRedis) -> ChatEventBus:
    return ChatEventBus(redis=fake_redis)


@pytest.fixture
def session_task_ids() -> tuple[uuid.UUID, uuid.UUID]:
    return uuid.uuid4(), uuid.uuid4()


async def test_xadd_event_returns_entry_id(
    bus: ChatEventBus, session_task_ids: tuple[uuid.UUID, uuid.UUID]
) -> None:
    sid, tid = session_task_ids
    entry_id = await bus.xadd_event(sid, tid, {"type": "token", "text": "hello"})
    # Redis stream id format: <ms>-<seq>
    assert "-" in entry_id
    ms_str, seq_str = entry_id.split("-")
    assert ms_str.isdigit()
    assert seq_str.isdigit()


async def test_xread_blocking_from_zero_returns_all(
    bus: ChatEventBus, session_task_ids: tuple[uuid.UUID, uuid.UUID]
) -> None:
    sid, tid = session_task_ids
    await bus.xadd_event(sid, tid, {"type": "token", "text": "a"})
    await bus.xadd_event(sid, tid, {"type": "token", "text": "b"})
    entries = await bus.xread_blocking(sid, tid, last_id="0", count=10, block_ms=10)
    assert len(entries) == 2
    assert entries[0][1]["type"] == "token"
    assert entries[0][1]["text"] == "a"
    assert entries[1][1]["text"] == "b"


async def test_xread_blocking_with_last_id_returns_only_new(
    bus: ChatEventBus, session_task_ids: tuple[uuid.UUID, uuid.UUID]
) -> None:
    sid, tid = session_task_ids
    first = await bus.xadd_event(sid, tid, {"type": "token", "text": "a"})
    await bus.xadd_event(sid, tid, {"type": "token", "text": "b"})
    entries = await bus.xread_blocking(sid, tid, last_id=first, count=10, block_ms=10)
    assert len(entries) == 1
    assert entries[0][1]["text"] == "b"


async def test_xread_blocking_empty_stream_returns_empty(
    bus: ChatEventBus, session_task_ids: tuple[uuid.UUID, uuid.UUID]
) -> None:
    sid, tid = session_task_ids
    entries = await bus.xread_blocking(sid, tid, last_id="0", count=10, block_ms=10)
    assert entries == []


async def test_set_ttl_marks_stream_for_expiry(
    bus: ChatEventBus,
    fake_redis: FakeRedis,
    session_task_ids: tuple[uuid.UUID, uuid.UUID],
) -> None:
    sid, tid = session_task_ids
    await bus.xadd_event(sid, tid, {"type": "token", "text": "x"})
    await bus.set_ttl(sid, tid, seconds=86400)
    key = bus._stream_key(sid, tid)
    pttl = await fake_redis.pttl(key)
    # 24h = 86_400_000 ms; allow ±10s tolerance for fakeredis timing quirks
    assert 86_000_000 < pttl <= 86_400_001


async def test_xadd_event_handles_large_payload(
    bus: ChatEventBus, session_task_ids: tuple[uuid.UUID, uuid.UUID]
) -> None:
    sid, tid = session_task_ids
    large_text = "x" * 5000  # 5KB
    entry_id = await bus.xadd_event(sid, tid, {"type": "token", "text": large_text})
    entries = await bus.xread_blocking(sid, tid, last_id="0", count=1, block_ms=10)
    assert len(entries) == 1
    assert entries[0][1]["text"] == large_text
    assert entries[0][0] == entry_id


async def test_stream_key_isolation(
    bus: ChatEventBus, session_task_ids: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """两个不同 session/task 的 stream 必须不互相串流。"""
    sid1, tid1 = session_task_ids
    sid2, tid2 = uuid.uuid4(), uuid.uuid4()
    await bus.xadd_event(sid1, tid1, {"type": "token", "text": "a"})
    await bus.xadd_event(sid2, tid2, {"type": "token", "text": "b"})
    entries_1 = await bus.xread_blocking(sid1, tid1, last_id="0", count=10, block_ms=10)
    assert len(entries_1) == 1
    assert entries_1[0][1]["text"] == "a"
