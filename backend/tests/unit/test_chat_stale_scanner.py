# mypy: disable-error-code="arg-type"
# SQLAlchemy Column[UUID] 在 instance attr 上 mypy 推断不准(runtime 是 UUID,
# 静态视为 Column[UUID])— 测试代码 silence,与 test_chat_task_repo.py 同。
"""Stale scanner L0 unit。

测试覆盖:
- 10 min 老 running task → mark_error + emit stale error event 到 Redis Stream
- 2 min running(< 5min cutoff)→ untouched
- done task → untouched(即使 0 min cutoff)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest_asyncio
from app.core.database import Base
from app.models.chat import ChatSession, ChatTask
from app.models.user import User  # noqa: F401
from app.services.chat_event_bus import ChatEventBus
from app.services.chat_task_repo import ChatTaskRepo
from app.tasks.chat_stale_scanner import scan_stale_chat_tasks_async
from fakeredis.aioredis import FakeRedis
from sqlalchemy import update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

_REQUIRED = ("users", "chat_sessions", "chat_tasks", "chat_messages")


def _selective_create_all(sync_conn: object) -> None:
    Base.metadata.create_all(sync_conn, tables=[Base.metadata.tables[n] for n in _REQUIRED])


@pytest_asyncio.fixture
async def session_factory():
    engine: AsyncEngine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(_selective_create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_task(session_factory, *, age_minutes: int, mark_done: bool = False):
    sid = uuid.uuid4()
    async with session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()
    repo = ChatTaskRepo(session_factory)
    task = await repo.create_queued(
        session_id=sid,
        user_id=uuid.uuid4(),
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await repo.mark_running(task.id)
    if mark_done:
        await repo.mark_done(task.id, langgraph_checkpoint_id=None)
    old_time = datetime.utcnow() - timedelta(minutes=age_minutes)
    async with session_factory() as sess:
        await sess.execute(
            update(ChatTask).where(ChatTask.id == task.id).values(started_at=old_time)
        )
        await sess.commit()
    return sid, task.id


async def test_scanner_marks_stale_task_as_error(session_factory):
    """10 min old running → status=error + error_message contains 'stale'。"""
    sid, tid = await _seed_task(session_factory, age_minutes=10)
    fake_redis = FakeRedis(decode_responses=False)

    n_marked = await scan_stale_chat_tasks_async(
        session_factory=session_factory,
        redis=fake_redis,
        stale_minutes=5,
    )
    assert n_marked == 1

    repo = ChatTaskRepo(session_factory)
    task = await repo.get_by_id(tid)
    assert task is not None
    assert task.status == "error"
    assert task.error_message is not None
    assert "stale" in task.error_message.lower()


async def test_scanner_emits_stale_error_event_to_redis_stream(session_factory):
    sid, tid = await _seed_task(session_factory, age_minutes=10)
    fake_redis = FakeRedis(decode_responses=False)

    await scan_stale_chat_tasks_async(
        session_factory=session_factory,
        redis=fake_redis,
        stale_minutes=5,
    )

    bus = ChatEventBus(fake_redis)
    entries = await bus.xread_blocking(sid, tid, last_id="0", count=10, block_ms=10)
    # 应有 error_done event,reason='stale'
    has_stale = any(
        e[1].get("type") in ("error", "error_done") and ("stale" in str(e[1]).lower())
        for e in entries
    )
    assert has_stale, f"expected stale error event, got {[e[1] for e in entries]}"


async def test_scanner_skips_fresh_running_task(session_factory):
    sid, tid = await _seed_task(session_factory, age_minutes=2)  # 2 min < 5 min cutoff
    fake_redis = FakeRedis(decode_responses=False)
    n = await scan_stale_chat_tasks_async(
        session_factory=session_factory,
        redis=fake_redis,
        stale_minutes=5,
    )
    assert n == 0

    repo = ChatTaskRepo(session_factory)
    task = await repo.get_by_id(tid)
    assert task is not None
    assert task.status == "running"  # untouched


async def test_scanner_skips_done_task(session_factory):
    """已完成 task 即使 started_at 古老,也不算 stale(status filter)。"""
    sid, tid = await _seed_task(session_factory, age_minutes=10, mark_done=True)
    fake_redis = FakeRedis(decode_responses=False)
    n = await scan_stale_chat_tasks_async(
        session_factory=session_factory,
        redis=fake_redis,
        stale_minutes=0,
    )
    assert n == 0
