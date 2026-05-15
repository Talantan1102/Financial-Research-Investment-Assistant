"""L1 — /api/v0/chats CRUD endpoints with mocked repo."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_chats():
    """Build a minimal FastAPI app with chats router + mocked repo override."""
    from app.router.chats import get_repo, router

    app = FastAPI()
    app.include_router(router)

    fake_id = uuid4()
    fake_session = SimpleNamespace(
        id=fake_id,
        title="test",
        user_id="anonymous",
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
    # Task 7: default no in-flight task
    repo.find_active_task_for_session = AsyncMock(return_value=None)

    app.dependency_overrides[get_repo] = lambda: repo
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
