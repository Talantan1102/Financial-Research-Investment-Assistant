"""L1 — /api/v0/chats CRUD endpoints with mocked repo."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.router.auth_router import get_current_user_required
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Stable owner identity shared between the seeded session and the default
# authenticated user, so the happy-path tests authenticate AS the owner.
_OWNER_ID = uuid4()


@pytest.fixture
def app_with_chats():
    """Build a minimal FastAPI app with chats router + mocked repo override.

    Auth is overridden to the session owner by default (happy path); tests that
    exercise cross-user isolation re-override get_current_user_required.
    """
    from app.router.chats import get_repo, router

    app = FastAPI()
    app.include_router(router)

    fake_id = uuid4()
    fake_session = SimpleNamespace(
        id=fake_id,
        title="test",
        user_id=_OWNER_ID,
        updated_at=datetime.utcnow(),
        message_count=0,
        last_msg_preview="",
    )

    repo = AsyncMock()
    repo.create_session = AsyncMock(return_value=fake_session)
    repo.list_for_user = AsyncMock(return_value=[fake_session])
    repo.get_session = AsyncMock(return_value=fake_session)
    repo.list_messages = AsyncMock(return_value=[])
    repo.delete_session = AsyncMock(return_value=None)
    repo.rename_session = AsyncMock(return_value=None)
    # Task 7: default no in-flight task
    repo.find_active_task_for_session = AsyncMock(return_value=None)

    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_current_user_required] = lambda: SimpleNamespace(id=_OWNER_ID)
    return app, repo, fake_id


def test_create_chat(app_with_chats):
    app, repo, _ = app_with_chats
    client = TestClient(app)
    r = client.post("/api/v0/chats/", json={"title": "test"})
    assert r.status_code == 200
    assert r.json()["title"] == "test"
    repo.create_session.assert_awaited_once()


def test_list_chats(app_with_chats):
    app, repo, _ = app_with_chats
    client = TestClient(app)
    r = client.get("/api/v0/chats/")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) == 1


def test_get_chat(app_with_chats):
    app, repo, fake_id = app_with_chats
    client = TestClient(app)
    r = client.get(f"/api/v0/chats/{fake_id}")
    assert r.status_code == 200
    assert "session" in r.json()
    assert "messages" in r.json()


def test_get_chat_404(app_with_chats):
    app, repo, _ = app_with_chats
    repo.get_session = AsyncMock(return_value=None)
    client = TestClient(app)
    r = client.get(f"/api/v0/chats/{uuid4()}")
    assert r.status_code == 404


def test_delete_chat(app_with_chats):
    app, repo, fake_id = app_with_chats
    client = TestClient(app)
    r = client.delete(f"/api/v0/chats/{fake_id}")
    assert r.status_code == 200
    assert r.json()["status"] == "deleted"
    repo.delete_session.assert_awaited_once()


def test_get_chat_returns_null_active_task_when_no_inflight(app_with_chats):
    """Task 7: 无 chat_task → active_task_id is null。每条 message 仍带 task_id/status 字段。"""
    app, repo, fake_id = app_with_chats
    # 一条 legacy 消息(没有 task_id)
    fake_msg = SimpleNamespace(
        id=uuid4(),
        role="user",
        content="hello",
        message_type="text",
        task_id=None,
        status="done",
        created_at=datetime.utcnow(),
    )
    repo.list_messages = AsyncMock(return_value=[fake_msg])
    repo.find_active_task_for_session = AsyncMock(return_value=None)

    client = TestClient(app)
    r = client.get(f"/api/v0/chats/{fake_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["active_task_id"] is None
    assert len(body["messages"]) == 1
    assert body["messages"][0]["task_id"] is None
    assert body["messages"][0]["status"] == "done"
    repo.find_active_task_for_session.assert_awaited_once()


def test_get_chat_returns_active_task_id_when_running(app_with_chats):
    """Task 7: 有 running chat_task → active_task_id is its UUID 串;message 携带 task_id。"""
    app, repo, fake_id = app_with_chats
    task_id = uuid4()
    fake_task = SimpleNamespace(id=task_id, status="running")
    fake_msg = SimpleNamespace(
        id=uuid4(),
        role="user",
        content="hello",
        message_type="text",
        task_id=task_id,
        status="partial",
        created_at=datetime.utcnow(),
    )
    repo.list_messages = AsyncMock(return_value=[fake_msg])
    repo.find_active_task_for_session = AsyncMock(return_value=fake_task)

    client = TestClient(app)
    r = client.get(f"/api/v0/chats/{fake_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["active_task_id"] == str(task_id)
    assert body["messages"][0]["task_id"] == str(task_id)
    assert body["messages"][0]["status"] == "partial"


# ---------------------------------------------------------------------------
# Data isolation — cross-user access must 404, missing auth must 401
# ---------------------------------------------------------------------------


def _auth_as_other_user(app) -> None:
    """Re-override auth to a DIFFERENT user than the session owner."""
    app.dependency_overrides[get_current_user_required] = lambda: SimpleNamespace(id=uuid4())


def _drop_auth_override(app) -> None:
    """Remove the auth override so the real get_current_user_required runs.

    Stub get_db too so the 401 path (no token) never touches a real PG session.
    """
    from app.core.database import get_db

    app.dependency_overrides.pop(get_current_user_required, None)

    def _dummy_db():
        yield None

    app.dependency_overrides[get_db] = _dummy_db


def test_get_chat_404_when_not_owner(app_with_chats):
    app, repo, fake_id = app_with_chats
    _auth_as_other_user(app)
    client = TestClient(app)
    r = client.get(f"/api/v0/chats/{fake_id}")
    assert r.status_code == 404


def test_rename_chat_404_when_not_owner(app_with_chats):
    app, repo, fake_id = app_with_chats
    _auth_as_other_user(app)
    client = TestClient(app)
    r = client.put(f"/api/v0/chats/{fake_id}", json={"title": "hijacked"})
    assert r.status_code == 404
    repo.rename_session.assert_not_awaited()


def test_delete_chat_404_when_not_owner(app_with_chats):
    app, repo, fake_id = app_with_chats
    _auth_as_other_user(app)
    client = TestClient(app)
    r = client.delete(f"/api/v0/chats/{fake_id}")
    assert r.status_code == 404
    repo.delete_session.assert_not_awaited()


def test_get_chat_401_without_auth(app_with_chats):
    app, repo, fake_id = app_with_chats
    _drop_auth_override(app)
    client = TestClient(app)
    r = client.get(f"/api/v0/chats/{fake_id}")
    assert r.status_code == 401


def test_list_chats_401_without_auth(app_with_chats):
    app, repo, _ = app_with_chats
    _drop_auth_override(app)
    client = TestClient(app)
    r = client.get("/api/v0/chats/")
    assert r.status_code == 401
