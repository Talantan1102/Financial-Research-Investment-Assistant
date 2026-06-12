# mypy: disable-error-code="arg-type, return-value"
"""chats.py 用户隔离回归:无 token 401 / A·B 各看各 / 越权 404(IDOR 堵死)。

C.6 chat 子系统接真 auth 后,会话列表/CRUD 必须按 user.id 隔离。
"""

from __future__ import annotations

import uuid

import pytest
from app.router.auth_router import get_current_user_required
from app.router.chats import get_repo
from app.router.chats import router as chats_router
from app.services.chat_session_repo import ChatSessionRepo
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text


class _U:
    def __init__(self, uid: uuid.UUID) -> None:
        self.id = uid


def _make_user(factory: object) -> uuid.UUID:
    """Insert a users row (FK target for chat_sessions.user_id)."""
    import asyncio

    uid = uuid.uuid4()

    async def _ins() -> None:
        async with factory() as sess:  # type: ignore[operator]
            await sess.execute(
                text(
                    "INSERT INTO users (id, username, email, hashed_password, is_active) "
                    "VALUES (:id, :u, :e, :p, true)"
                ),
                {
                    "id": str(uid),
                    "u": f"iso_{uid.hex[:8]}",
                    "e": f"{uid.hex[:8]}@t.local",
                    "p": "x",
                },
            )
            await sess.commit()

    asyncio.run(_ins())
    return uid


@pytest.fixture
def repo(pg_async_session_factory: object) -> ChatSessionRepo:
    return ChatSessionRepo(pg_async_session_factory)


def _client(repo: ChatSessionRepo, user: _U | None) -> TestClient:
    app = FastAPI()
    app.include_router(chats_router)
    app.dependency_overrides[get_repo] = lambda: repo
    if user is not None:
        app.dependency_overrides[get_current_user_required] = lambda: user
    return TestClient(app, raise_server_exceptions=True)


def test_unauth_list_is_401(repo: ChatSessionRepo) -> None:
    """无 token → 401(不再返全量会话)。"""
    client = _client(repo, user=None)
    # 不 override get_current_user_required → 真依赖,无 token → 401
    assert client.get("/api/v0/chats").status_code == 401


def test_list_isolated_per_user(repo: ChatSessionRepo, pg_async_session_factory: object) -> None:
    a = _U(_make_user(pg_async_session_factory))
    b = _U(_make_user(pg_async_session_factory))

    ca = _client(repo, a)
    sid_a = ca.post("/api/v0/chats", json={"title": "A的会话"}).json()["id"]
    assert any(s["id"] == sid_a for s in ca.get("/api/v0/chats").json())

    cb = _client(repo, b)
    assert all(s["id"] != sid_a for s in cb.get("/api/v0/chats").json())


def test_idor_blocked_get_rename_delete(
    repo: ChatSessionRepo, pg_async_session_factory: object
) -> None:
    a = _U(_make_user(pg_async_session_factory))
    b = _U(_make_user(pg_async_session_factory))
    ca = _client(repo, a)
    sid_a = ca.post("/api/v0/chats", json={"title": "A only"}).json()["id"]

    cb = _client(repo, b)
    assert cb.get(f"/api/v0/chats/{sid_a}").status_code == 404
    assert cb.put(f"/api/v0/chats/{sid_a}", json={"title": "hijack"}).status_code == 404
    assert cb.delete(f"/api/v0/chats/{sid_a}").status_code == 404
    # A 自己仍可访问
    assert ca.get(f"/api/v0/chats/{sid_a}").status_code == 200


def _make_session_task(factory: object, owner: uuid.UUID) -> uuid.UUID:
    """建一个归属 owner 的 session + queued task,返回 task_id(供任务型端点 IDOR 测)。"""
    import asyncio

    from app.models.chat import ChatSession
    from app.services.chat_task_repo import ChatTaskRepo

    sid = uuid.uuid4()

    async def _mk() -> uuid.UUID:
        async with factory() as sess:  # type: ignore[operator]
            sess.add(ChatSession(id=sid, user_id=owner, title="A"))
            await sess.commit()
        task = await ChatTaskRepo(factory).create_queued(
            session_id=sid,
            user_id=owner,
            langgraph_thread_id="t",
            initial_prompt_message_id=None,
        )
        return task.id

    return asyncio.run(_mk())


def test_chat_task_endpoint_idor_blocked(pg_async_session_factory: object) -> None:
    """任务型端点(cancel)归属校验:B 不能 cancel A 的 task → 404。"""
    from app.router.chat import get_async_session_factory, get_redis_async
    from app.router.chat import router as chat_router
    from fakeredis.aioredis import FakeRedis

    a = _U(_make_user(pg_async_session_factory))
    b = _U(_make_user(pg_async_session_factory))
    task_id = _make_session_task(pg_async_session_factory, a.id)

    fr = FakeRedis(decode_responses=False)
    app = FastAPI()
    app.include_router(chat_router)
    app.dependency_overrides[get_async_session_factory] = lambda: pg_async_session_factory
    app.dependency_overrides[get_redis_async] = lambda: fr
    app.dependency_overrides[get_current_user_required] = lambda: b  # B,非 owner A
    client = TestClient(app, raise_server_exceptions=True)
    assert client.post(f"/api/v0/chat/cancel/{task_id}").status_code == 404
