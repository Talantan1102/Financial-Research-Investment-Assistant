# mypy: disable-error-code="arg-type"
"""数据隔离 — chat task/session 端点拒绝跨用户访问(统一 404)。

owned_task fixture 用真 User 行 + 真 UUID 持有一个 session+task;测试以另一个
用户身份打 stream/cancel/steer/retry/POST /chat,断言 404(防越权 + 防枚举)。
无 token → get_current_user_required 抛 401。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from app.models.chat import ChatSession
from app.models.user import User
from app.router.chat import (
    get_async_session_factory,
    get_current_user_required,
    get_redis_async,
)
from app.router.chat import router as chat_router
from app.services.chat_task_repo import ChatTaskRepo
from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class _User:
    def __init__(self, uid: uuid.UUID) -> None:
        self.id = uid


@pytest.fixture
def session_factory(
    pg_async_session_factory: async_sessionmaker[AsyncSession],
) -> async_sessionmaker[AsyncSession]:
    return pg_async_session_factory


@pytest_asyncio.fixture
async def fake_redis() -> AsyncIterator[FakeRedis]:
    r = FakeRedis(decode_responses=False)
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def owned_task(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, Any]:
    """A session + running task owned by user A (a real User row, real UUID)."""
    owner = uuid.uuid4()
    sid = uuid.uuid4()
    tag = uuid.uuid4().hex[:8]
    async with session_factory() as sess:
        sess.add(
            User(
                id=owner,
                username=f"owner-{tag}",
                email=f"owner-{tag}@test",
                hashed_password="x",
                is_active=True,
            )
        )
        sess.add(ChatSession(id=sid, user_id=owner, title="t"))
        await sess.commit()
    task_repo = ChatTaskRepo(session_factory)
    task = await task_repo.create_queued(
        session_id=sid,
        user_id=owner,
        langgraph_thread_id=f"{owner}:{sid}",
        initial_prompt_message_id=None,
    )
    await task_repo.mark_running(task.id)
    return {"owner": owner, "session_id": sid, "task_id": task.id}


def _client_as(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis_obj: FakeRedis,
    user_id: uuid.UUID | None,
) -> TestClient:
    app = FastAPI()
    app.include_router(chat_router)
    if user_id is not None:
        app.dependency_overrides[get_current_user_required] = lambda: _User(user_id)
    app.dependency_overrides[get_async_session_factory] = lambda: session_factory
    app.dependency_overrides[get_redis_async] = lambda: fake_redis_obj
    return TestClient(app, raise_server_exceptions=True)


@pytest.mark.asyncio
async def test_stream_404_for_other_users_task(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    owned_task: dict[str, Any],
) -> None:
    client = _client_as(session_factory, fake_redis, uuid.uuid4())
    r = client.get(f"/api/v0/chat/stream/{owned_task['task_id']}?last_event_id=0")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_cancel_404_for_other_users_task(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    owned_task: dict[str, Any],
) -> None:
    client = _client_as(session_factory, fake_redis, uuid.uuid4())
    r = client.post(f"/api/v0/chat/cancel/{owned_task['task_id']}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_steer_404_for_other_users_task(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    owned_task: dict[str, Any],
) -> None:
    client = _client_as(session_factory, fake_redis, uuid.uuid4())
    r = client.post(f"/api/v0/chat/steer/{owned_task['task_id']}", json={"message": "hijack"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_retry_404_for_other_users_task(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    owned_task: dict[str, Any],
) -> None:
    client = _client_as(session_factory, fake_redis, uuid.uuid4())
    r = client.post(f"/api/v0/chat/retry/{owned_task['task_id']}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_post_chat_404_for_other_users_session(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    owned_task: dict[str, Any],
) -> None:
    client = _client_as(session_factory, fake_redis, uuid.uuid4())
    r = client.post(
        "/api/v0/chat",
        json={"session_id": str(owned_task["session_id"]), "message": "inject"},
    )
    assert r.status_code == 404


def test_stream_401_without_auth(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
) -> None:
    """No auth override → real get_current_user_required → no token → 401."""
    client = _client_as(session_factory, fake_redis, user_id=None)
    r = client.get(f"/api/v0/chat/stream/{uuid.uuid4()}")
    assert r.status_code == 401
