"""C41: Regression test — PUT /api/v0/chats/{id} (rename) delegates to repo.rename_session.

session_router.py was deleted as dead code (never registered in app_main.py);
chats.py is the active endpoint.  This test guards the rename path in chats.py
so the deletion does not reduce functional coverage.

Key assertion: repo.rename_session is called with the correct session_id and title,
which in turn sets title_source='user_renamed' (tested exhaustively in
tests/unit/services/test_chat_session_repo.py::test_rename_session_executes_update).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.router.auth_router import get_current_user_required
from fastapi import FastAPI
from fastapi.testclient import TestClient

_OWNER_ID = uuid.uuid4()


@pytest.fixture
def app_with_chats_rename():
    """Minimal FastAPI app wiring chats router with a mock repo.

    Auth is overridden to the session owner (forced-login happy path).
    """
    from app.router.chats import get_repo, router

    app = FastAPI()
    app.include_router(router)

    fake_id = uuid.uuid4()
    fake_session = SimpleNamespace(
        id=fake_id,
        title="旧标题",
        user_id=_OWNER_ID,
        updated_at=datetime.utcnow(),
        message_count=0,
        last_msg_preview="",
    )
    updated_session = SimpleNamespace(
        id=fake_id,
        title="新标题",
        user_id=_OWNER_ID,
        updated_at=datetime.utcnow(),
        message_count=0,
        last_msg_preview="",
    )

    repo = AsyncMock()
    # First get_session (existence check) returns original; second (re-fetch) returns updated.
    repo.get_session = AsyncMock(side_effect=[fake_session, updated_session])
    repo.rename_session = AsyncMock(return_value=None)
    repo.find_active_task_for_session = AsyncMock(return_value=None)

    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_current_user_required] = lambda: SimpleNamespace(id=_OWNER_ID)
    return app, repo, fake_id


def test_put_chat_calls_rename_session(app_with_chats_rename):
    """PUT /api/v0/chats/{id} must call repo.rename_session with the new title.

    repo.rename_session is responsible for setting title_source='user_renamed'
    (see test_chat_session_repo.py::test_rename_session_executes_update).
    """
    app, repo, fake_id = app_with_chats_rename
    client = TestClient(app)

    resp = client.put(f"/api/v0/chats/{fake_id}", json={"title": "新标题"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "新标题"

    # C41: guard that rename_session is invoked — it is the contract point for
    # title_source='user_renamed' (SSOT: the repo sets it, not the router).
    repo.rename_session.assert_awaited_once_with(str(fake_id), "新标题")


def test_put_chat_returns_404_for_unknown_session(app_with_chats_rename):
    """PUT /api/v0/chats/{id} on a missing session returns 404."""
    app, repo, _ = app_with_chats_rename
    repo.get_session = AsyncMock(return_value=None)
    client = TestClient(app)

    unknown_id = uuid.uuid4()
    resp = client.put(f"/api/v0/chats/{unknown_id}", json={"title": "任意标题"})

    assert resp.status_code == 404
    repo.rename_session.assert_not_awaited()
