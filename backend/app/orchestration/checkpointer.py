"""SqliteSaver / AsyncSqliteSaver checkpointer factories for graph persistence."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import aiosqlite
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

DEFAULT_DB_PATH = Path("backend/data/chat.sqlite")
DEFAULT_RESEARCH_DB_PATH = Path("backend/data/research.sqlite")


def make_chat_checkpointer(db_path: Path = DEFAULT_DB_PATH) -> SqliteSaver:
    """Create and return a SqliteSaver backed by a SQLite file at *db_path*.

    Parent directories are created automatically. The connection is opened
    with check_same_thread=False so that LangGraph's async machinery can
    share it across threads.

    Args:
        db_path: Path to the SQLite database file. Defaults to
                 ``backend/data/chat.sqlite`` (relative to CWD, which is
                 the worktree root when invoked from CI or ``uv run``).

    Returns:
        A configured :class:`langgraph.checkpoint.sqlite.SqliteSaver`.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    return SqliteSaver(conn)


async def make_async_chat_checkpointer(
    db_path: Path = DEFAULT_RESEARCH_DB_PATH,
) -> AsyncSqliteSaver:
    """Create and return an AsyncSqliteSaver backed by a SQLite file at *db_path*.

    Must be called from within a running asyncio event loop (e.g., inside an
    async FastAPI dependency or lifespan handler).  The caller owns the returned
    saver's lifecycle — the underlying ``aiosqlite`` connection is left open so
    that LangGraph can reuse it across requests.  Call
    ``await saver.conn.close()`` when the application shuts down.

    Use this factory for any graph that is driven via ``graph.astream_events()``
    or ``graph.ainvoke()`` in an async context.  The sync ``SqliteSaver`` raises
    "does not support async methods" when used with those APIs.

    Args:
        db_path: Path to the SQLite database file. Defaults to
                 ``backend/data/research.sqlite``.

    Returns:
        A configured :class:`langgraph.checkpoint.sqlite.aio.AsyncSqliteSaver`.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn: aiosqlite.Connection = await aiosqlite.connect(str(db_path))
    return AsyncSqliteSaver(conn)
