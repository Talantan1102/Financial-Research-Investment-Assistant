"""L0 — SqliteSaver checkpointer factory tests."""

from __future__ import annotations

from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


def test_make_checkpointer_returns_sqlitesaver(tmp_path: Path) -> None:
    """make_chat_checkpointer returns a SqliteSaver instance."""
    from app.orchestration.checkpointer import make_chat_checkpointer

    saver = make_chat_checkpointer(tmp_path / "chat.sqlite")
    assert isinstance(saver, SqliteSaver)


def test_make_checkpointer_creates_parent_dir(tmp_path: Path) -> None:
    """make_chat_checkpointer creates deep parent directories as needed."""
    from app.orchestration.checkpointer import make_chat_checkpointer

    deep_path = tmp_path / "deep" / "nested" / "chat.sqlite"
    assert not deep_path.parent.exists()
    make_chat_checkpointer(deep_path)
    assert deep_path.parent.exists()


def test_make_checkpointer_idempotent_on_existing_dir(tmp_path: Path) -> None:
    """make_chat_checkpointer succeeds even when parent dir already exists."""
    from app.orchestration.checkpointer import make_chat_checkpointer

    db_path = tmp_path / "chat.sqlite"
    # Call twice — should not raise on existing parent
    saver1 = make_chat_checkpointer(db_path)
    saver2 = make_chat_checkpointer(db_path)
    assert isinstance(saver1, SqliteSaver)
    assert isinstance(saver2, SqliteSaver)
