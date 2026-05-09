"""L0 — ChatMessage v0.9 schema.

Tests verify v0.9 fields exist on the ORM mapper with correct column
definitions (default, nullable).  We check mapper-level Column metadata
rather than instantiated-object attribute values because SQLAlchemy only
applies `default=` callables at INSERT/flush time, not at __init__ time.
"""

from __future__ import annotations

from app.models.chat import ChatMessage, ChatSession
from sqlalchemy import inspect


def _col(model_class, name):
    """Return the SQLAlchemy Column object for a mapped attribute name."""
    mapper = inspect(model_class)
    return mapper.columns[name]


# ---------------------------------------------------------------------------
# ChatMessage v0.9 fields
# ---------------------------------------------------------------------------


def test_chatmessage_message_type_column_exists_with_text_default():
    col = _col(ChatMessage, "message_type")
    assert col is not None
    assert not col.nullable
    # Python-level default (fires at INSERT)
    assert col.default is not None
    assert col.default.arg == "text"
    # server_default for DDL migrations
    assert col.server_default is not None


def test_chatmessage_research_report_id_nullable():
    col = _col(ChatMessage, "research_report_id")
    assert col is not None
    assert col.nullable


def test_chatmessage_research_report_summary_nullable():
    col = _col(ChatMessage, "research_report_summary")
    assert col is not None
    assert col.nullable


def test_chatmessage_tool_call_data_nullable():
    col = _col(ChatMessage, "tool_call_data")
    assert col is not None
    assert col.nullable


# ---------------------------------------------------------------------------
# ChatSession v0.9 fields
# ---------------------------------------------------------------------------


def test_chatsession_message_count_column_exists_with_zero_default():
    col = _col(ChatSession, "message_count")
    assert col is not None
    assert not col.nullable
    assert col.default is not None
    assert col.default.arg == 0


def test_chatsession_last_msg_preview_nullable():
    col = _col(ChatSession, "last_msg_preview")
    assert col is not None
    assert col.nullable
