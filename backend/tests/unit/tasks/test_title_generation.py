"""L0 unit tests for generate_session_title Celery task.

覆盖:
- title_source != "pending" → skip
- len(messages) < 2 → skip (防御)
- LLM 返回带引号/「」 → strip 干净
- LLM 输出 > 255 字 → 截断
- LLM 全失败 → fallback user.content[:20] + "..."
- 成功路径 → title_source 变 llm_generated
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest  # noqa: F401
from app.models.chat import ChatMessage, ChatSession
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def db_with_session(monkeypatch):
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    engine = create_engine("sqlite:///:memory:")
    ChatSession.__table__.create(bind=engine)
    ChatMessage.__table__.create(bind=engine)
    Session = sessionmaker(bind=engine)
    sid = uuid.uuid4()
    with Session() as sess:
        sess.add(ChatSession(id=sid, title="新对话", title_source="pending"))
        sess.add(
            ChatMessage(
                id=uuid.uuid4(),
                session_id=sid,
                role="user",
                content="贵州茅台最近怎么样,值得现在买入吗?",
                status="done",
            )
        )
        sess.add(
            ChatMessage(
                id=uuid.uuid4(),
                session_id=sid,
                role="assistant",
                content="贵州茅台当前 PE 约 25x, 历史百分位 35%, ...",
                status="done",
            )
        )
        sess.commit()
    return engine, str(sid), Session


def _patch_db(monkeypatch, Session):
    """让 task 使用我们的 in-memory engine."""
    import app.tasks.title_generation as mod

    monkeypatch.setattr(mod, "_open_db_session", lambda: Session())


def test_skip_when_title_source_not_pending(db_with_session, monkeypatch):
    engine, sid, Session = db_with_session
    with Session() as sess:
        s = sess.query(ChatSession).filter_by(id=uuid.UUID(sid)).one()
        s.title_source = "user_renamed"
        sess.commit()
    _patch_db(monkeypatch, Session)

    from app.tasks.title_generation import generate_session_title

    mock_llm = MagicMock()
    with patch("app.tasks.title_generation.get_llm_service", return_value=mock_llm):
        generate_session_title(sid)
    mock_llm.chat.assert_not_called()


def test_skip_when_less_than_two_messages(monkeypatch):
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    engine = create_engine("sqlite:///:memory:")
    ChatSession.__table__.create(bind=engine)
    ChatMessage.__table__.create(bind=engine)
    Session = sessionmaker(bind=engine)
    sid = uuid.uuid4()
    with Session() as sess:
        sess.add(ChatSession(id=sid, title="新对话", title_source="pending"))
        sess.add(
            ChatMessage(id=uuid.uuid4(), session_id=sid, role="user", content="hi", status="done")
        )
        sess.commit()
    _patch_db(monkeypatch, Session)

    from app.tasks.title_generation import generate_session_title

    mock_llm = MagicMock()
    with patch("app.tasks.title_generation.get_llm_service", return_value=mock_llm):
        generate_session_title(str(sid))
    mock_llm.chat.assert_not_called()


def test_strips_quotes_and_brackets(db_with_session, monkeypatch):
    engine, sid, Session = db_with_session
    _patch_db(monkeypatch, Session)

    mock_llm = MagicMock()
    mock_llm.chat.return_value = MagicMock(content="「贵州茅台估值分析」")

    from app.tasks.title_generation import generate_session_title

    with patch("app.tasks.title_generation.get_llm_service", return_value=mock_llm):
        generate_session_title(sid)
    with Session() as sess:
        s = sess.query(ChatSession).filter_by(id=uuid.UUID(sid)).one()
        assert s.title == "贵州茅台估值分析"
        assert s.title_source == "llm_generated"


def test_truncates_oversized_title(db_with_session, monkeypatch):
    engine, sid, Session = db_with_session
    _patch_db(monkeypatch, Session)

    mock_llm = MagicMock()
    mock_llm.chat.return_value = MagicMock(content="a" * 500)

    from app.tasks.title_generation import generate_session_title

    with patch("app.tasks.title_generation.get_llm_service", return_value=mock_llm):
        generate_session_title(sid)
    with Session() as sess:
        s = sess.query(ChatSession).filter_by(id=uuid.UUID(sid)).one()
        assert len(s.title) <= 255


def test_fallback_when_llm_keeps_failing(db_with_session, monkeypatch):
    engine, sid, Session = db_with_session
    _patch_db(monkeypatch, Session)

    mock_llm = MagicMock()
    mock_llm.chat.side_effect = RuntimeError("LLM down")

    from app.tasks.title_generation import generate_session_title

    with patch("app.tasks.title_generation.get_llm_service", return_value=mock_llm):
        generate_session_title(sid)
    with Session() as sess:
        s = sess.query(ChatSession).filter_by(id=uuid.UUID(sid)).one()
        # fallback: user.content[:20] + "..."
        expected = "贵州茅台最近怎么样,值得现在买入吗?"[:20] + "..."
        assert s.title == expected
        assert s.title_source == "llm_generated"


def test_success_path_writes_llm_generated(db_with_session, monkeypatch):
    engine, sid, Session = db_with_session
    _patch_db(monkeypatch, Session)

    mock_llm = MagicMock()
    mock_llm.chat.return_value = MagicMock(content="贵州茅台估值分析")

    from app.tasks.title_generation import generate_session_title

    with patch("app.tasks.title_generation.get_llm_service", return_value=mock_llm):
        generate_session_title(sid)
    with Session() as sess:
        s = sess.query(ChatSession).filter_by(id=uuid.UUID(sid)).one()
        assert s.title == "贵州茅台估值分析"
        assert s.title_source == "llm_generated"
