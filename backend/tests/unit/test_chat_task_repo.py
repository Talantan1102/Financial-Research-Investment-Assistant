# mypy: disable-error-code="arg-type"
# SQLAlchemy classical Column[UUID] 在 instance attr 上 mypy 推断不准
# (task.id 实际是 UUID runtime,mypy 视为 Column[UUID])— 测试代码 silence。
"""ChatTaskRepo 单元测试 — 6 状态机 + Repo 方法集。

测试策略:in-memory sqlite + 选择性 create_all(只建 users / chat_sessions /
chat_tasks 三张表;chat_messages / long_term_memories 含 JSONB / ARRAY 这些
PG-only 类型,sqlite 编译会炸 — Repo 不依赖这两张表,所以跳过)。
sqlite 默认不强制 FK,因此 chat_tasks.initial_prompt_message_id 指向未建的
chat_messages 表也没问题。

覆盖 9 个 method + 状态机的核心转换路径。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime

import pytest_asyncio
from app.core.database import Base
from app.models.chat import ChatSession
from app.models.user import User  # noqa: F401 — 注册 users 表
from app.services.chat_task_repo import ChatTaskRepo
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Repo 真实使用的表(不含 PG-only JSONB/ARRAY 字段);保证 sqlite 编译通过
_REQUIRED_TABLE_NAMES = ("users", "chat_sessions", "chat_tasks")


def _selective_create_all(sync_conn: object) -> None:
    tables = [Base.metadata.tables[name] for name in _REQUIRED_TABLE_NAMES]
    Base.metadata.create_all(sync_conn, tables=tables)


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine: AsyncEngine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(_selective_create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> uuid.UUID:
    """种一个 ChatSession 让 ChatTask 的 session_id FK 有对应行。"""
    sid = uuid.uuid4()
    async with session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()
    return sid


# -----------------------------------------------------------------------------
# create_queued
# -----------------------------------------------------------------------------


async def test_create_queued_inserts_row(
    session_factory: async_sessionmaker[AsyncSession],
    seeded_session: uuid.UUID,
) -> None:
    repo = ChatTaskRepo(session_factory)
    user_id = uuid.uuid4()
    task = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=user_id,
        langgraph_thread_id=f"{user_id}:{seeded_session}",
        initial_prompt_message_id=None,
    )
    assert task.status == "queued"
    assert task.session_id == seeded_session
    assert task.user_id == user_id
    assert task.langgraph_thread_id == f"{user_id}:{seeded_session}"
    assert task.last_event_seq == 0
    assert task.started_at is None


# -----------------------------------------------------------------------------
# mark_running
# -----------------------------------------------------------------------------


async def test_mark_running_sets_started_at(
    session_factory: async_sessionmaker[AsyncSession],
    seeded_session: uuid.UUID,
) -> None:
    repo = ChatTaskRepo(session_factory)
    task = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=uuid.uuid4(),
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
    session_factory: async_sessionmaker[AsyncSession],
    seeded_session: uuid.UUID,
) -> None:
    repo = ChatTaskRepo(session_factory)
    task = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=uuid.uuid4(),
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
    session_factory: async_sessionmaker[AsyncSession],
    seeded_session: uuid.UUID,
) -> None:
    repo = ChatTaskRepo(session_factory)
    task = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=uuid.uuid4(),
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
    session_factory: async_sessionmaker[AsyncSession],
    seeded_session: uuid.UUID,
) -> None:
    repo = ChatTaskRepo(session_factory)
    task = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=uuid.uuid4(),
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
    session_factory: async_sessionmaker[AsyncSession],
    seeded_session: uuid.UUID,
) -> None:
    repo = ChatTaskRepo(session_factory)
    task = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=uuid.uuid4(),
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
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repo = ChatTaskRepo(session_factory)
    fetched = await repo.get_by_id(uuid.uuid4())
    assert fetched is None


# -----------------------------------------------------------------------------
# find_active_for_session
# -----------------------------------------------------------------------------


async def test_find_active_for_session_returns_queued_or_running(
    session_factory: async_sessionmaker[AsyncSession],
    seeded_session: uuid.UUID,
) -> None:
    repo = ChatTaskRepo(session_factory)
    user_id = uuid.uuid4()
    t1 = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=user_id,
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
    session_factory: async_sessionmaker[AsyncSession],
    seeded_session: uuid.UUID,
) -> None:
    """Plan 2 用,Plan 1 先实现 + 测,避免 Plan 2 时翻 schema。"""
    repo = ChatTaskRepo(session_factory)
    task = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=uuid.uuid4(),
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
