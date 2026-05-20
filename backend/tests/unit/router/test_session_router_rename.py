"""PUT /sessions/{id} 写 title 时, title_source 同步置 user_renamed."""

from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from app.core.database import get_db
from app.router.auth_router import get_current_user_required
from app.router.session_router import router as session_router
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _FakeUser:
    """Lightweight stand-in for User — avoids SQLAlchemy ORM instrumentation."""

    def __init__(self, user_id: uuid.UUID) -> None:
        self.id = user_id
        self.email = "t@x.com"


class _FakeChatSession:
    """Lightweight stand-in for ChatSession ORM — avoids SQLite UUID dialect issues.

    The session_router only reads/writes .title, .title_source on the returned
    session object; it does not call any ORM relationship accessors.
    """

    def __init__(self, sid: uuid.UUID, user_id: uuid.UUID) -> None:
        self.id = sid
        self.user_id = user_id
        self.title = "新对话"
        self.title_source = "llm_generated"
        self.session_type = "chat"
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        self.message_count = 0
        self.last_msg_preview = None


@pytest.fixture
def client_with_seed() -> Generator[tuple[TestClient, uuid.UUID, _FakeChatSession], None, None]:
    """Minimal FastAPI app with mocked DB — avoids PG/SQLite UUID dialect issues."""
    sid = uuid.uuid4()
    user_id = uuid.uuid4()

    fake_user = _FakeUser(user_id)
    chat_session = _FakeChatSession(sid, user_id)

    # Build a mock DB that returns our fake session on query().filter().first()
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = chat_session
    mock_query.filter.return_value = mock_filter
    mock_db.query.return_value = mock_query

    # func.count scalar for message_count in session_to_response
    mock_count_query = MagicMock()
    mock_count_filter = MagicMock()
    mock_count_filter.scalar.return_value = 0
    mock_count_query.filter.return_value = mock_count_filter
    # Second call to db.query (for count) returns mock_count_query
    mock_db.query.side_effect = [mock_query, mock_count_query]

    def _get_db() -> Generator[MagicMock, None, None]:
        yield mock_db

    app = FastAPI()
    app.include_router(session_router)
    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user_required] = lambda: fake_user

    yield TestClient(app), sid, chat_session

    app.dependency_overrides.clear()


def test_put_session_sets_user_renamed(
    client_with_seed: tuple[TestClient, uuid.UUID, _FakeChatSession],
) -> None:
    client, sid, chat_session = client_with_seed
    resp = client.put(f"/sessions/{sid}", json={"title": "我自己起的名字"})
    assert resp.status_code == 200, resp.text

    # Verify the ORM object got both attributes set
    assert chat_session.title == "我自己起的名字"
    assert chat_session.title_source == "user_renamed"
