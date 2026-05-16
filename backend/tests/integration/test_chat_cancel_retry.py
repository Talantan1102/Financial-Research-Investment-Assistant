# mypy: disable-error-code="arg-type"
"""Plan 3 L1 集成测试 — POST /chat/retry/{tid} + worker resume from checkpoint。

测试覆盖:
- task 有 langgraph_checkpoint_id → retry 创建新 task(parent_task_id=旧 tid)+ enqueue 时
  传 resume_checkpoint_id,前端拿到新 task_id + stream_url
- task 无 langgraph_checkpoint_id → 422(cannot resume)
- task status != error/partial/cancelled → 409(只有失败 task 能 retry)
- 404 for unknown task_id
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from app.core.database import Base
from app.models.chat import ChatSession, ChatTask
from app.models.user import User  # noqa: F401 — registers users table
from app.router.chat import (
    get_async_session_factory,
    get_chat_graph,
    get_current_user,
    get_escalation_extractor,
    get_escalation_record_repo,
    get_redis_async,
)
from app.router.chat import router as chat_router
from app.services.chat_task_repo import ChatTaskRepo
from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_REQUIRED_TABLE_NAMES = ("users", "chat_sessions", "chat_tasks", "chat_messages")


def _selective_create_all(sync_conn: object) -> None:
    tables = [Base.metadata.tables[name] for name in _REQUIRED_TABLE_NAMES]
    Base.metadata.create_all(sync_conn, tables=tables)


class _StubUser:
    def __init__(self) -> None:
        self.id = "test-user"


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine: AsyncEngine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(_selective_create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def fake_redis() -> AsyncIterator[FakeRedis]:
    r = FakeRedis(decode_responses=False)
    yield r
    await r.aclose()


def _client(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis_obj: FakeRedis,
) -> TestClient:
    app = FastAPI()
    app.include_router(chat_router)
    app.dependency_overrides[get_chat_graph] = lambda: MagicMock()
    app.dependency_overrides[get_current_user] = lambda: _StubUser()
    app.dependency_overrides[get_escalation_extractor] = lambda: None
    app.dependency_overrides[get_escalation_record_repo] = lambda: None
    app.dependency_overrides[get_async_session_factory] = lambda: session_factory
    app.dependency_overrides[get_redis_async] = lambda: fake_redis_obj
    return TestClient(app, raise_server_exceptions=True)


@pytest.mark.asyncio
async def test_post_retry_with_checkpoint_enqueues_resume_task(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failed task with checkpoint_id → retry 创建新 task,parent 链接旧 tid。"""
    enqueued: list[dict[str, Any]] = []
    from app.tasks import chat_runner

    def fake_enqueue(**kwargs: Any) -> Any:
        enqueued.append(kwargs)

        class _R:
            def __init__(self, tid: str) -> None:
                self.id = tid

        return _R(kwargs["task_id"])

    monkeypatch.setattr(chat_runner, "enqueue_run_chat", fake_enqueue)

    # Seed session + error task with checkpoint_id
    sid = uuid.uuid4()
    async with session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()

    task_repo = ChatTaskRepo(session_factory)
    old_task = await task_repo.create_queued(
        session_id=sid,
        user_id=uuid.uuid4(),
        langgraph_thread_id=f"u:{sid}",
        initial_prompt_message_id=None,
    )
    await task_repo.mark_running(old_task.id)
    await task_repo.mark_error(old_task.id, error_message="simulated crash")
    async with session_factory() as sess:
        await sess.execute(
            sql_update(ChatTask)
            .where(ChatTask.id == old_task.id)
            .values(langgraph_checkpoint_id="ckpt-resume-x")
        )
        await sess.commit()

    client = _client(session_factory, fake_redis)
    resp = client.post(f"/api/v0/chat/retry/{old_task.id}")
    assert resp.status_code == 200, f"got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert "task_id" in body
    new_tid = body["task_id"]
    assert new_tid != str(old_task.id)
    assert body.get("parent_task_id") == str(old_task.id)
    assert body.get("resumed_from_checkpoint") == "ckpt-resume-x"
    assert "stream_url" in body
    assert new_tid in body["stream_url"]

    # Verify enqueue called with resume_checkpoint_id
    assert len(enqueued) == 1
    assert enqueued[0]["resume_checkpoint_id"] == "ckpt-resume-x"
    assert enqueued[0]["task_id"] == new_tid

    # 新 chat_tasks row 存在,parent_task_id 链接
    new_task = await task_repo.get_by_id(uuid.UUID(new_tid))
    assert new_task is not None
    assert new_task.parent_task_id == old_task.id


@pytest.mark.asyncio
async def test_post_retry_without_checkpoint_returns_422(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
) -> None:
    """Failed task 没 checkpoint_id → 422 cannot resume。"""
    sid = uuid.uuid4()
    async with session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()
    task_repo = ChatTaskRepo(session_factory)
    old_task = await task_repo.create_queued(
        session_id=sid,
        user_id=uuid.uuid4(),
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await task_repo.mark_error(old_task.id, error_message="early failure")

    client = _client(session_factory, fake_redis)
    resp = client.post(f"/api/v0/chat/retry/{old_task.id}")
    assert resp.status_code == 422
    assert "checkpoint" in resp.text.lower() or "resume" in resp.text.lower()


@pytest.mark.asyncio
async def test_post_retry_running_task_returns_409(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
) -> None:
    """status=running 不能 retry(正在跑)。"""
    sid = uuid.uuid4()
    async with session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()
    task_repo = ChatTaskRepo(session_factory)
    task = await task_repo.create_queued(
        session_id=sid,
        user_id=uuid.uuid4(),
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await task_repo.mark_running(task.id)

    client = _client(session_factory, fake_redis)
    resp = client.post(f"/api/v0/chat/retry/{task.id}")
    assert resp.status_code == 409


def test_post_retry_404_for_unknown_task(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
) -> None:
    """Unknown task_id → 404。"""
    client = _client(session_factory, fake_redis)
    fake_tid = uuid.uuid4()
    resp = client.post(f"/api/v0/chat/retry/{fake_tid}")
    assert resp.status_code == 404
