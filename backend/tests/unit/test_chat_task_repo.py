# mypy: disable-error-code="arg-type"
# SQLAlchemy classical Column[UUID] 在 instance attr 上 mypy 推断不准
# (task.id 实际是 UUID runtime,mypy 视为 Column[UUID])— 测试代码 silence。
"""ChatTaskRepo 单元测试 — 6 状态机 + Repo 方法集。

测试策略:真 PG(industry_assistant_test) + async_session_factory fixture。
pg_test_engine(session-scoped) 已在 session 开始时 create_all,
每个 test 用唯一 UUID 保证行级隔离,无 cross-test 污染。

覆盖 9 个 method + 状态机的核心转换路径。
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest_asyncio
from app.models.chat import ChatSession
from app.models.user import User  # noqa: F401 — 注册 users 表
from app.services.chat_task_repo import ChatTaskRepo
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def seeded_session(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> uuid.UUID:
    """种一个 ChatSession 让 ChatTask 的 session_id FK 有对应行。"""
    sid = uuid.uuid4()
    async with async_session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()
    return sid


# -----------------------------------------------------------------------------
# create_queued
# -----------------------------------------------------------------------------


async def test_create_queued_inserts_row(
    async_session_factory: async_sessionmaker[AsyncSession],
    seeded_session: uuid.UUID,
) -> None:
    repo = ChatTaskRepo(async_session_factory)
    task = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=None,  # nullable FK; PG enforces FK so we skip random UUID
        langgraph_thread_id=f"t:{seeded_session}",
        initial_prompt_message_id=None,
    )
    assert task.status == "queued"
    assert task.session_id == seeded_session
    assert task.user_id is None
    assert task.langgraph_thread_id == f"t:{seeded_session}"
    assert task.last_event_seq == 0
    assert task.started_at is None


# -----------------------------------------------------------------------------
# mark_running
# -----------------------------------------------------------------------------


async def test_mark_running_sets_started_at(
    async_session_factory: async_sessionmaker[AsyncSession],
    seeded_session: uuid.UUID,
) -> None:
    repo = ChatTaskRepo(async_session_factory)
    task = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=None,  # nullable FK; PG enforces FK so we use None
        langgraph_thread_id="t1",
        initial_prompt_message_id=None,
    )
    before = datetime.utcnow()
    await repo.mark_running(task.id)
    fetched = await repo.get_by_id(task.id)
    assert fetched is not None
    assert fetched.status == "running"
    assert fetched.started_at is not None
    assert fetched.started_at >= before


# -----------------------------------------------------------------------------
# mark_done
# -----------------------------------------------------------------------------


async def test_mark_done_sets_finished_at_and_checkpoint(
    async_session_factory: async_sessionmaker[AsyncSession],
    seeded_session: uuid.UUID,
) -> None:
    repo = ChatTaskRepo(async_session_factory)
    task = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=None,  # nullable FK; PG enforces FK so we use None
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await repo.mark_running(task.id)
    await repo.mark_done(task.id, langgraph_checkpoint_id="ckpt-abc")
    fetched = await repo.get_by_id(task.id)
    assert fetched is not None
    assert fetched.status == "done"
    assert fetched.finished_at is not None
    assert fetched.langgraph_checkpoint_id == "ckpt-abc"


# -----------------------------------------------------------------------------
# mark_partial
# -----------------------------------------------------------------------------


async def test_mark_partial_keeps_checkpoint(
    async_session_factory: async_sessionmaker[AsyncSession],
    seeded_session: uuid.UUID,
) -> None:
    repo = ChatTaskRepo(async_session_factory)
    task = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=None,  # nullable FK; PG enforces FK so we use None
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await repo.mark_running(task.id)
    await repo.mark_partial(task.id, langgraph_checkpoint_id="ckpt-x")
    fetched = await repo.get_by_id(task.id)
    assert fetched is not None
    assert fetched.status == "partial"
    assert fetched.langgraph_checkpoint_id == "ckpt-x"


# -----------------------------------------------------------------------------
# mark_cancelled
# -----------------------------------------------------------------------------


async def test_mark_cancelled_no_checkpoint_needed(
    async_session_factory: async_sessionmaker[AsyncSession],
    seeded_session: uuid.UUID,
) -> None:
    repo = ChatTaskRepo(async_session_factory)
    task = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=None,  # nullable FK; PG enforces FK so we use None
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await repo.mark_running(task.id)
    await repo.mark_cancelled(task.id, langgraph_checkpoint_id=None)
    fetched = await repo.get_by_id(task.id)
    assert fetched is not None
    assert fetched.status == "cancelled"
    assert fetched.langgraph_checkpoint_id is None


# -----------------------------------------------------------------------------
# mark_error
# -----------------------------------------------------------------------------


async def test_mark_error_sets_error_message(
    async_session_factory: async_sessionmaker[AsyncSession],
    seeded_session: uuid.UUID,
) -> None:
    repo = ChatTaskRepo(async_session_factory)
    task = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=None,  # nullable FK; PG enforces FK so we use None
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await repo.mark_running(task.id)
    await repo.mark_error(task.id, error_message="LLM 429 rate limited")
    fetched = await repo.get_by_id(task.id)
    assert fetched is not None
    assert fetched.status == "error"
    assert fetched.error_message == "LLM 429 rate limited"


# -----------------------------------------------------------------------------
# get_by_id
# -----------------------------------------------------------------------------


async def test_get_by_id_returns_none_for_unknown(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repo = ChatTaskRepo(async_session_factory)
    fetched = await repo.get_by_id(uuid.uuid4())
    assert fetched is None


# -----------------------------------------------------------------------------
# find_active_for_session
# -----------------------------------------------------------------------------


async def test_find_active_for_session_returns_queued_or_running(
    async_session_factory: async_sessionmaker[AsyncSession],
    seeded_session: uuid.UUID,
) -> None:
    repo = ChatTaskRepo(async_session_factory)
    t1 = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=None,  # nullable FK; PG enforces FK so we use None
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await repo.mark_running(t1.id)

    active = await repo.find_active_for_session(seeded_session)
    assert active is not None
    assert active.id == t1.id

    await repo.mark_done(t1.id, langgraph_checkpoint_id=None)
    active_after = await repo.find_active_for_session(seeded_session)
    assert active_after is None


# -----------------------------------------------------------------------------
# bump_seq
# -----------------------------------------------------------------------------


async def test_bump_seq_increments_last_event_seq(
    async_session_factory: async_sessionmaker[AsyncSession],
    seeded_session: uuid.UUID,
) -> None:
    """Plan 2 用,Plan 1 先实现 + 测,避免 Plan 2 时翻 schema。"""
    repo = ChatTaskRepo(async_session_factory)
    task = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=None,  # nullable FK; PG enforces FK so we use None
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await repo.bump_seq(task.id, delta=5)
    fetched = await repo.get_by_id(task.id)
    assert fetched is not None
    assert fetched.last_event_seq == 5

    await repo.bump_seq(task.id, delta=3)
    fetched2 = await repo.get_by_id(task.id)
    assert fetched2 is not None
    assert fetched2.last_event_seq == 8


# -----------------------------------------------------------------------------
# find_stale_running_tasks (Plan 3)
# -----------------------------------------------------------------------------


async def test_find_stale_running_tasks_returns_old_running(
    async_session_factory: async_sessionmaker[AsyncSession],
    seeded_session: uuid.UUID,
) -> None:
    """status=running 且 started_at 早于 cutoff → 视为 stale。"""
    repo = ChatTaskRepo(async_session_factory)
    task = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=None,  # nullable FK; PG enforces FK so we use None
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await repo.mark_running(task.id)

    # 直接 update started_at 为 10 分钟前
    from datetime import timedelta

    from app.models.chat import ChatTask
    from sqlalchemy import update

    old_time = datetime.utcnow() - timedelta(minutes=10)
    async with async_session_factory() as sess:
        await sess.execute(
            update(ChatTask).where(ChatTask.id == task.id).values(started_at=old_time)
        )
        await sess.commit()

    stale = await repo.find_stale_running_tasks(min_age_minutes=5)
    assert any(t.id == task.id for t in stale), (
        f"expected task in stale list, got {[t.id for t in stale]}"
    )


async def test_find_stale_running_tasks_excludes_recent_running(
    async_session_factory: async_sessionmaker[AsyncSession],
    seeded_session: uuid.UUID,
) -> None:
    """刚 mark_running 的 task(started_at < 5min ago)→ 不算 stale。"""
    repo = ChatTaskRepo(async_session_factory)
    task = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=None,  # nullable FK; PG enforces FK so we use None
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await repo.mark_running(task.id)

    stale = await repo.find_stale_running_tasks(min_age_minutes=5)
    assert all(t.id != task.id for t in stale), "fresh running task should not be stale"


async def test_find_stale_running_tasks_excludes_done(
    async_session_factory: async_sessionmaker[AsyncSession],
    seeded_session: uuid.UUID,
) -> None:
    """已完成 task 不算 stale。"""
    repo = ChatTaskRepo(async_session_factory)
    task = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=None,  # nullable FK; PG enforces FK so we use None
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await repo.mark_running(task.id)
    await repo.mark_done(task.id, langgraph_checkpoint_id=None)

    stale = await repo.find_stale_running_tasks(min_age_minutes=0)
    assert all(t.id != task.id for t in stale), "done task should not be stale"
