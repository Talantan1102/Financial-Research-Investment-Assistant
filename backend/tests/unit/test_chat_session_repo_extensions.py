# mypy: disable-error-code="arg-type"
# SQLAlchemy classical Column[UUID] 在 instance attr 上 mypy 推断不准
# (task.id 实际是 UUID runtime,mypy 视为 Column[UUID])— 测试代码 silence。
"""ChatSessionRepo Plan 1 扩展测试。

新增:
- append_message(task_id=..., status=...) 兼容现有签名,新参数可选
- find_active_task_for_session(sid) 委托 ChatTaskRepo 实现

测试策略:真 PG(industry_assistant_test) + async_session_factory fixture。
pg_test_engine(session-scoped) 已在 session 开始时 create_all,
每个 test 用唯一 UUID 保证行级隔离。
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from app.models.chat import ChatSession
from app.models.user import User  # noqa: F401 — 注册 users 表
from app.services.chat_session_repo import ChatSessionRepo
from app.services.chat_task_repo import ChatTaskRepo
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def seeded(async_session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    sid = uuid.uuid4()
    async with async_session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()
    return sid


@pytest.mark.asyncio
async def test_append_message_without_task_keeps_legacy_behavior(
    async_session_factory: async_sessionmaker[AsyncSession], seeded: uuid.UUID
) -> None:
    """legacy 路径(escalation)不传 task_id 应该照常 work,默认 status=done。"""
    repo = ChatSessionRepo(async_session_factory)
    msg = await repo.append_message(
        session_id=str(seeded),
        role="user",
        content="hello",
    )
    assert msg.task_id is None
    assert msg.status == "done"


@pytest.mark.asyncio
async def test_append_message_with_task_id_and_partial_status(
    async_session_factory: async_sessionmaker[AsyncSession], seeded: uuid.UUID
) -> None:
    """Plan 1 新路径:落 assistant 消息时关联 task + 标 partial 状态。"""
    repo = ChatSessionRepo(async_session_factory)
    task_repo = ChatTaskRepo(async_session_factory)
    task = await task_repo.create_queued(
        session_id=str(seeded),
        user_id=None,  # nullable FK; PG enforces FK so we use None
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    msg = await repo.append_message(
        session_id=str(seeded),
        role="assistant",
        content="partial answer",
        task_id=task.id,
        status="partial",
    )
    assert msg.task_id == task.id
    assert msg.status == "partial"


@pytest.mark.asyncio
async def test_find_active_task_for_session_no_active(
    async_session_factory: async_sessionmaker[AsyncSession], seeded: uuid.UUID
) -> None:
    repo = ChatSessionRepo(async_session_factory)
    active = await repo.find_active_task_for_session(seeded)
    assert active is None


@pytest.mark.asyncio
async def test_find_active_task_for_session_returns_running(
    async_session_factory: async_sessionmaker[AsyncSession], seeded: uuid.UUID
) -> None:
    repo = ChatSessionRepo(async_session_factory)
    task_repo = ChatTaskRepo(async_session_factory)
    task = await task_repo.create_queued(
        session_id=str(seeded),
        user_id=None,  # nullable FK; PG enforces FK so we use None
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await task_repo.mark_running(task.id)
    active = await repo.find_active_task_for_session(seeded)
    assert active is not None
    assert active.id == task.id


@pytest.mark.asyncio
async def test_list_messages_includes_task_and_status(
    async_session_factory: async_sessionmaker[AsyncSession], seeded: uuid.UUID
) -> None:
    """list_messages 返回的 ChatMessage 应该带 task_id 和 status 字段
    (model 已有,这里守护 serialize 路径)。
    """
    repo = ChatSessionRepo(async_session_factory)
    task_repo = ChatTaskRepo(async_session_factory)
    task = await task_repo.create_queued(
        session_id=str(seeded),
        user_id=None,  # nullable FK; PG enforces FK so we use None
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await repo.append_message(
        session_id=str(seeded),
        role="assistant",
        content="ans",
        task_id=task.id,
        status="done",
    )
    msgs = await repo.list_messages(str(seeded))
    assert len(msgs) == 1
    assert msgs[0].task_id == task.id
    assert msgs[0].status == "done"
