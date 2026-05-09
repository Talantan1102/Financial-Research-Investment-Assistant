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
