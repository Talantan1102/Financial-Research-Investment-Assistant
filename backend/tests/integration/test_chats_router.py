"""L1 — /api/v0/chats CRUD endpoints and paper approval history."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.router.auth_router import get_current_user_required
from app.router.chats import get_repo, router

_OWNER = uuid4()


class _U:
    def __init__(self, uid: object) -> None:
        self.id = uid


@pytest.fixture
def app_with_chats():
    app = FastAPI()
    app.include_router(router)
    fake_id = uuid4()
    fake_session = SimpleNamespace(id=fake_id, title="test", user_id=_OWNER, updated_at=datetime.utcnow(), message_count=0, last_msg_preview="")
    repo = AsyncMock()
    repo.create_session = AsyncMock(return_value=fake_session)
    repo.list_for_user = AsyncMock(return_value=[fake_session])
    repo.get_session = AsyncMock(return_value=fake_session)
    repo.list_messages = AsyncMock(return_value=[])
    repo.delete_session = AsyncMock(return_value=None)
    repo.find_active_task_for_session = AsyncMock(return_value=None)
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_current_user_required] = lambda: _U(_OWNER)
    return app, repo, fake_id


def test_create_chat(app_with_chats):
    app, repo, _ = app_with_chats
    r = TestClient(app).post("/api/v0/chats/", json={"title": "test"})
    assert r.status_code == 200 and r.json()["title"] == "test"
    repo.create_session.assert_awaited_once()


def test_list_chats(app_with_chats):
    app, _, _ = app_with_chats
    r = TestClient(app).get("/api/v0/chats/")
    assert r.status_code == 200 and len(r.json()) == 1


def test_get_chat(app_with_chats):
    app, _, fake_id = app_with_chats
    r = TestClient(app).get(f"/api/v0/chats/{fake_id}")
    assert r.status_code == 200 and "messages" in r.json()


def test_get_chat_404(app_with_chats):
    app, repo, _ = app_with_chats
    repo.get_session = AsyncMock(return_value=None)
    assert TestClient(app).get(f"/api/v0/chats/{uuid4()}").status_code == 404


def test_delete_chat(app_with_chats):
    app, repo, fake_id = app_with_chats
    r = TestClient(app).delete(f"/api/v0/chats/{fake_id}")
    assert r.status_code == 200 and r.json()["status"] == "deleted"
    repo.delete_session.assert_awaited_once()


def test_get_chat_returns_active_task_id_when_running(app_with_chats):
    app, repo, fake_id = app_with_chats
    task_id = uuid4()
    repo.find_active_task_for_session = AsyncMock(return_value=SimpleNamespace(id=task_id, status="running"))
    repo.list_messages = AsyncMock(return_value=[SimpleNamespace(id=uuid4(), role="user", content="hello", message_type="text", task_id=task_id, status="partial", created_at=datetime.utcnow())])
    body = TestClient(app).get(f"/api/v0/chats/{fake_id}").json()
    assert body["active_task_id"] == str(task_id)


def test_history_returns_paper_approval_payload() -> None:
    uid, sid = uuid4(), uuid4()
    approval = {"approval_id": "a1", "approval_type": "paper_order", "resource_id": "o1", "proposal": {}, "preview": {}, "expires_at": datetime.now().isoformat()}
    msg = SimpleNamespace(id=uuid4(), role="assistant", content="请确认", message_type="paper_approval", tool_call_data=approval, task_id=None, status="done", created_at=datetime.now())
    session = SimpleNamespace(id=sid, user_id=uid, title="x", updated_at=datetime.now())

    class Repo:
        async def get_session(self, _sid): return session
        async def list_messages(self, _sid): return [msg]
        async def find_active_task_for_session(self, _sid): return None

    app = FastAPI(); app.include_router(router)
    app.dependency_overrides[get_repo] = lambda: Repo()
    app.dependency_overrides[get_current_user_required] = lambda: SimpleNamespace(id=uid)
    body = TestClient(app).get(f"/api/v0/chats/{sid}").json()
    assert body["messages"][0]["tool_call_data"] == approval
