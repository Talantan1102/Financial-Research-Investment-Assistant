# mypy: disable-error-code="arg-type"
# SQLAlchemy Column[UUID] 在 instance attr 上 mypy 推断不准(runtime 是 UUID,
# 静态视为 Column[UUID])— 测试代码 silence,与 test_chat_task_repo.py 同。
"""Stale scanner L0 unit。

测试覆盖:
- 10 min 老 running task → mark_error + emit stale error event 到 Redis Stream
- 2 min running(< 5min cutoff)→ untouched
- done task → untouched(即使 0 min cutoff)

测试策略:真 PG(industry_assistant_test) + async_session_factory fixture。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from app.models.chat import ChatSession, ChatTask
from app.models.user import User  # noqa: F401
from app.services.chat_event_bus import ChatEventBus
from app.services.chat_task_repo import ChatTaskRepo
from app.tasks.chat_stale_scanner import scan_stale_chat_tasks_async
from fakeredis.aioredis import FakeRedis
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def _seed_task(
    async_session_factory: async_sessionmaker[AsyncSession],
    *,
    age_minutes: int,
    mark_done: bool = False,
) -> tuple[uuid.UUID, uuid.UUID]:
    sid = uuid.uuid4()
    async with async_session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()
    repo = ChatTaskRepo(async_session_factory)
    task = await repo.create_queued(
        session_id=sid,
        user_id=None,  # nullable FK; PG enforces FK so we use None
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await repo.mark_running(task.id)
    if mark_done:
        await repo.mark_done(task.id, langgraph_checkpoint_id=None)
    old_time = datetime.utcnow() - timedelta(minutes=age_minutes)
    async with async_session_factory() as sess:
        await sess.execute(
            update(ChatTask).where(ChatTask.id == task.id).values(started_at=old_time)
        )
        await sess.commit()
    return sid, task.id


async def test_scanner_marks_stale_task_as_error(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """10 min old running → status=error + error_message contains 'stale'。

    n_marked >= 1 (shared PG: other tests may have left stale tasks too).
    We verify OUR specific task was marked.
    """
    sid, tid = await _seed_task(async_session_factory, age_minutes=10)
    fake_redis = FakeRedis(decode_responses=False)

    n_marked = await scan_stale_chat_tasks_async(
        session_factory=async_session_factory,
        redis=fake_redis,
        stale_minutes=5,
    )
    assert n_marked >= 1  # at least our seeded task

    repo = ChatTaskRepo(async_session_factory)
    task = await repo.get_by_id(tid)
    assert task is not None
    assert task.status == "error"
    assert task.error_message is not None
    assert "stale" in task.error_message.lower()


async def test_scanner_emits_stale_error_event_to_redis_stream(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    sid, tid = await _seed_task(async_session_factory, age_minutes=10)
    fake_redis = FakeRedis(decode_responses=False)

    await scan_stale_chat_tasks_async(
        session_factory=async_session_factory,
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


async def test_scanner_skips_fresh_running_task(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    sid, tid = await _seed_task(async_session_factory, age_minutes=2)  # 2 min < 5 min cutoff
    fake_redis = FakeRedis(decode_responses=False)
    # n may be > 0 due to leftover tasks from other tests in shared PG.
    # We only care that OUR fresh task was NOT marked stale.
    await scan_stale_chat_tasks_async(
        session_factory=async_session_factory,
        redis=fake_redis,
        stale_minutes=5,
    )

    repo = ChatTaskRepo(async_session_factory)
    task = await repo.get_by_id(tid)
    assert task is not None
    assert task.status == "running"  # untouched


async def test_scanner_skips_done_task(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """已完成 task 即使 started_at 古老,也不算 stale(status filter)。

    n may be > 0 due to other running tasks in shared PG.
    We only care that OUR done task was NOT re-marked as error.
    """
    sid, tid = await _seed_task(async_session_factory, age_minutes=10, mark_done=True)
    fake_redis = FakeRedis(decode_responses=False)
    await scan_stale_chat_tasks_async(
        session_factory=async_session_factory,
        redis=fake_redis,
        stale_minutes=0,
    )
    repo = ChatTaskRepo(async_session_factory)
    task = await repo.get_by_id(tid)
    assert task is not None
    assert task.status == "done"  # done tasks are never re-marked stale
