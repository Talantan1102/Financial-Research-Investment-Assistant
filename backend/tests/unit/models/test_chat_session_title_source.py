"""Verify ChatSession.title_source field exists with correct default."""

from __future__ import annotations

import uuid

from app.models.chat import ChatSession
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_title_source_defaults_to_pending() -> None:
    """Verify ORM applies default='pending' when title_source is omitted at insert."""
    engine = create_engine("sqlite:///:memory:")
    ChatSession.__table__.create(bind=engine)
    Session = sessionmaker(bind=engine)
    with Session() as sess:
        s = ChatSession(id=uuid.uuid4(), user_id=None, title="t")
        # intentionally do NOT pass title_source — verify default kicks in
        sess.add(s)
        sess.commit()
        sess.refresh(s)
        assert s.title_source == "pending"


def test_title_source_accepts_three_values() -> None:
    """Column exists and all three accepted values round-trip via SQLite.

    We create only the chat_sessions table to avoid JSONB compilation errors
    from other models that use raw JSONB without a sqlite variant.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:")
    # Only create the chat_sessions table (avoids JSONB errors in other models)
    ChatSession.__table__.create(bind=engine)
    Session = sessionmaker(bind=engine)
    with Session() as sess:
        for source in ("pending", "llm_generated", "user_renamed"):
            s = ChatSession(
                id=uuid.uuid4(),
                user_id=None,
                title=f"t-{source}",
                title_source=source,
            )
            sess.add(s)
        sess.commit()
        rows = sess.query(ChatSession).all()
        assert {r.title_source for r in rows} == {"pending", "llm_generated", "user_renamed"}
