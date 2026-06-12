"""chats.py 用户隔离回归:无 token 401 / A·B 各看各 / 越权 404(IDOR 堵死)。

C.6 chat 子系统接真 auth 后,会话列表/CRUD 必须按 user.id 隔离。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

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
                {"id": str(uid), "u": f"iso_{uid.hex[:8]}", "e": f"{uid.hex[:8]}@t.local", "p": "x"},
            )
            await sess.commit()

    asyncio.get_event_loop().run_until_complete(_ins())
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
