"""L0 — ChatSessionRepo.

Uses AsyncMock / MagicMock session factory so no PG container needed.
The ChatSession.id is a UUID (ORM default); we assert uuid.UUID validity.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.services.chat_session_repo import ChatSessionRepo


@pytest.mark.asyncio
async def test_append_approval_once_checks_existing_id() -> None:
    sess = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = uuid.uuid4()
    sess.execute = AsyncMock(return_value=result)
    repo = ChatSessionRepo(_async_factory(sess))
    out = await repo.append_approval_once(
        session_id=str(uuid.uuid4()),
        approval_id="a1",
        content="x",
        tool_call_data={"approval_id": "a1"},
    )
    assert out is None
    sess.add.assert_not_called()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_row(user_id_str: str, title: str) -> MagicMock:
    """Return a mock ChatSession with realistic field values."""
    row = MagicMock()
    row.id = uuid.uuid4()
    row.user_id = uuid.UUID(user_id_str) if isinstance(user_id_str, str) else user_id_str
    row.title = title
    row.session_id = None  # not applicable
    return row


def _make_message_row(session_id: uuid.UUID, role: str, content: str) -> MagicMock:
    row = MagicMock()
    row.id = uuid.uuid4()
    row.session_id = session_id
    row.role = role
    row.content = content
    row.message_type = "text"
    return row


def _async_factory(sess: MagicMock):
    """Return an async context-manager factory yielding `sess`."""

    @asynccontextmanager
    async def factory():
        yield sess

    return factory


# ---------------------------------------------------------------------------
# create_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_session_calls_add_commit_refresh():
    """L0 — create_session adds row, commits, refreshes; returns ChatSession."""
    sess = MagicMock()
    sess.add = MagicMock()
    sess.commit = AsyncMock()
    sess.refresh = AsyncMock()

    user_id = str(uuid.uuid4())

    # patch ChatSession constructor so we control the returned row
    session_row = _make_session_row(user_id, "ICBC 尽调")

    with patch("app.services.chat_session_repo.ChatSession", return_value=session_row):
        repo = ChatSessionRepo(session_factory=_async_factory(sess))
        result = await repo.create_session(user_id=user_id, title="ICBC 尽调")

    assert result is session_row
    sess.add.assert_called_once_with(session_row)
    sess.commit.assert_awaited_once()
    sess.refresh.assert_awaited_once_with(session_row)


@pytest.mark.asyncio
async def test_create_session_result_has_uuid_id():
    """L0 — the returned row.id is a valid UUID (not a string prefix)."""
    sess = MagicMock()
    sess.add = MagicMock()
    sess.commit = AsyncMock()
    sess.refresh = AsyncMock()

    user_id = str(uuid.uuid4())
    session_row = _make_session_row(user_id, "test")

    with patch("app.services.chat_session_repo.ChatSession", return_value=session_row):
        repo = ChatSessionRepo(session_factory=_async_factory(sess))
        result = await repo.create_session(user_id=user_id, title="test")

    assert isinstance(result.id, uuid.UUID)


# ---------------------------------------------------------------------------
# list_for_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_for_user_executes_query_and_returns_scalars():
    """L0 — list_for_user executes a select and returns the scalars list."""
    user_id_str = str(uuid.uuid4())

    row_a = _make_session_row(user_id_str, "A")
    row_b = _make_session_row(user_id_str, "B")

    scalars_result = MagicMock()
    scalars_result.all.return_value = [row_a, row_b]

    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_result

    sess = MagicMock()
    sess.execute = AsyncMock(return_value=execute_result)

    repo = ChatSessionRepo(session_factory=_async_factory(sess))
    sessions = await repo.list_for_user(user_id_str)

    sess.execute.assert_awaited_once()
    assert len(sessions) == 2
    assert sessions[0] is row_a
    assert sessions[1] is row_b


# ---------------------------------------------------------------------------
# append_message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_append_message_adds_row_and_updates_session():
    """L0 — append_message inserts ChatMessage + bumps session updated_at."""
    session_id = uuid.uuid4()
    msg_row = _make_message_row(session_id, "user", "hello")

    sess = MagicMock()
    sess.add = MagicMock()
    sess.commit = AsyncMock()
    sess.refresh = AsyncMock()
    sess.execute = AsyncMock()

    with patch("app.services.chat_session_repo.ChatMessage", return_value=msg_row):
        repo = ChatSessionRepo(session_factory=_async_factory(sess))
        result = await repo.append_message(
            session_id=str(session_id),
            role="user",
            content="hello",
        )

    assert result is msg_row
    assert result.session_id == session_id
    sess.add.assert_called_once_with(msg_row)
    # execute called once for the UPDATE updated_at statement
    sess.execute.assert_awaited_once()
    sess.commit.assert_awaited_once()
    sess.refresh.assert_awaited_once_with(msg_row)


# ---------------------------------------------------------------------------
# list_messages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_messages_returns_ordered_rows():
    """L0 — list_messages executes select and returns ordered list."""
    session_id = uuid.uuid4()
    msg1 = _make_message_row(session_id, "user", "q1")
    msg2 = _make_message_row(session_id, "assistant", "a1")

    scalars_result = MagicMock()
    scalars_result.all.return_value = [msg1, msg2]

    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_result

    sess = MagicMock()
    sess.execute = AsyncMock(return_value=execute_result)

    repo = ChatSessionRepo(session_factory=_async_factory(sess))
    msgs = await repo.list_messages(str(session_id))

    sess.execute.assert_awaited_once()
    assert len(msgs) == 2
    assert msgs[0] is msg1
    assert msgs[1] is msg2


# ---------------------------------------------------------------------------
# rename_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rename_session_executes_update():
    """L0 — rename_session issues an UPDATE with title_source and commits."""
    sess = MagicMock()
    sess.execute = AsyncMock()
    sess.commit = AsyncMock()

    session_id = str(uuid.uuid4())
    repo = ChatSessionRepo(session_factory=_async_factory(sess))
    await repo.rename_session(session_id, "新标题")

    sess.execute.assert_awaited_once()
    sess.commit.assert_awaited_once()

    # Verify the UPDATE statement actually carries title_source="user_renamed"
    # in its .values(...) — guards against forgetting the terminal-rename sentinel.
    update_stmt = sess.execute.call_args[0][0]
    values = dict(update_stmt._values) if hasattr(update_stmt, "_values") else {}
    value_columns = [col.name if hasattr(col, "name") else str(col) for col in values]
    assert "title_source" in value_columns, (
        "UPDATE statement missing title_source column — "
        "rename_session must set title_source='user_renamed'"
    )
    assert "title" in value_columns, "UPDATE statement missing title column"
    # Also verify the actual bound values
    compiled = update_stmt.compile(compile_kwargs={"literal_binds": True})
    sql_str = str(compiled)
    assert "user_renamed" in sql_str, f"Expected 'user_renamed' in compiled SQL, got: {sql_str}"
    assert "新标题" in sql_str, f"Expected '新标题' in compiled SQL, got: {sql_str}"


# ---------------------------------------------------------------------------
# delete_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_session_removes_existing_row():
    """L0 — delete_session deletes existing row + commits."""
    session_id = uuid.uuid4()
    row = _make_session_row(str(uuid.uuid4()), "t")

    sess = MagicMock()
    sess.get = AsyncMock(return_value=row)
    sess.delete = AsyncMock()
    sess.commit = AsyncMock()

    repo = ChatSessionRepo(session_factory=_async_factory(sess))
    await repo.delete_session(str(session_id))

    sess.delete.assert_awaited_once_with(row)
    sess.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_session_noop_when_not_found():
    """L0 — delete_session is a noop if session_id not found."""
    sess = MagicMock()
    sess.get = AsyncMock(return_value=None)
    sess.delete = AsyncMock()
    sess.commit = AsyncMock()

    repo = ChatSessionRepo(session_factory=_async_factory(sess))
    await repo.delete_session(str(uuid.uuid4()))

    sess.delete.assert_not_awaited()
    sess.commit.assert_not_awaited()
