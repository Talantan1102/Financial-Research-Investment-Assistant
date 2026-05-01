"""SqliteSaver checkpointer factory for chat graph persistence."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

DEFAULT_DB_PATH = Path("backend/data/chat.sqlite")


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
