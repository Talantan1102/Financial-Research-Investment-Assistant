"""L0 unit tests for generate_session_title Celery task.

覆盖:
- title_source != "pending" → skip
- len(messages) < 2 → skip (防御)
- LLM 返回带引号/「」 → strip 干净
- LLM 输出 > 255 字 → 截断
- LLM 全失败 + content >20 字 → fallback user.content[:20] + "..."
- LLM 全失败 + content ≤20 字 → fallback user.content (无省略号)
- 成功路径 → title_source 变 llm_generated
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest  # noqa: F401
from app.models.chat import ChatMessage, ChatSession
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def db_with_session(pg_test_engine, monkeypatch):
    """PG-backed fixture (sqlite 被 PR-A 删了 with_variant fallback,
    Title test 原 sqlite:///:memory: 改用真 PG)。

    用 pg_test_engine 共享 schema(已 create_all),直接 sessionmaker bind。
    test 之间 TRUNCATE 自己用到的表清理 — 不走 db_session 是因为这些 test
    patch _open_db_session 要它自己开新 Session,跟 SAVEPOINT isolation 不兼容。
    """
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    # Cleanup before test: TRUNCATE the two tables we'll use.
    with pg_test_engine.connect() as conn:
        conn.execute(text("TRUNCATE TABLE chat_messages, chat_sessions CASCADE"))
        conn.commit()
    Session = sessionmaker(bind=pg_test_engine)
    sid = uuid.uuid4()
    with Session() as sess:
        sess.add(ChatSession(id=sid, title="新对话", title_source="pending"))
        sess.add(
            ChatMessage(
                id=uuid.uuid4(),
                session_id=sid,
                role="user",
                content="贵州茅台最近的财务表现怎么样,值得现在以这个价位买入吗?能否给我一些建议?",
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
    yield pg_test_engine, str(sid), Session
    # Cleanup after test.
    with pg_test_engine.connect() as conn:
        conn.execute(text("TRUNCATE TABLE chat_messages, chat_sessions CASCADE"))
        conn.commit()


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


def test_skip_when_no_user_message(pg_test_engine, monkeypatch):
    """Race: title task 跑前 user msg 还没 commit (or commit 失败) — 静默 skip 不调 LLM."""
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    with pg_test_engine.connect() as conn:
        conn.execute(text("TRUNCATE TABLE chat_messages, chat_sessions CASCADE"))
        conn.commit()
    Session = sessionmaker(bind=pg_test_engine)
    sid = uuid.uuid4()
    with Session() as sess:
        sess.add(ChatSession(id=sid, title="新对话", title_source="pending"))
        sess.commit()  # 只有 session, 0 个 user msg
    _patch_db(monkeypatch, Session)

    from app.tasks.title_generation import generate_session_title

    mock_llm = MagicMock()
    with patch("app.tasks.title_generation.get_llm_service", return_value=mock_llm):
        generate_session_title(str(sid))
    mock_llm.chat.assert_not_called()


def test_skip_when_session_deleted(pg_test_engine, monkeypatch):
    """Session 在 enqueue 和 task 启动之间被删除 - task 静默 return, 不调 LLM."""
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    with pg_test_engine.connect() as conn:
        conn.execute(text("TRUNCATE TABLE chat_messages, chat_sessions CASCADE"))
        conn.commit()
    Session = sessionmaker(bind=pg_test_engine)
    # 不 seed 任何 session — 直接调 task 用一个 random session_id
    _patch_db(monkeypatch, Session)

    from app.tasks.title_generation import generate_session_title

    mock_llm = MagicMock()
    with patch("app.tasks.title_generation.get_llm_service", return_value=mock_llm):
        generate_session_title(str(uuid.uuid4()))  # 任意 UUID, 数据库里不存在
    # 不应抛异常, 不应调 LLM
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
        # fallback: content >20 chars → user.content[:20] + "..."
        long_content = "贵州茅台最近的财务表现怎么样,值得现在以这个价位买入吗?能否给我一些建议?"
        assert len(long_content) > 20, "fixture content must be >20 chars to test truncation path"
        expected = long_content[:20] + "..."
        assert s.title == expected
        assert s.title_source == "llm_generated"


def test_fallback_short_content_no_ellipsis(pg_test_engine, monkeypatch):
    """LLM 全失败 + content ≤20 字 → fallback 返回原文,不追加省略号."""
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    with pg_test_engine.connect() as conn:
        conn.execute(text("TRUNCATE TABLE chat_messages, chat_sessions CASCADE"))
        conn.commit()
    Session = sessionmaker(bind=pg_test_engine)
    sid = uuid.uuid4()
    short_content = "hi"
    with Session() as sess:
        sess.add(ChatSession(id=sid, title="新对话", title_source="pending"))
        sess.add(
            ChatMessage(
                id=uuid.uuid4(),
                session_id=sid,
                role="user",
                content=short_content,
                status="done",
            )
        )
        sess.add(
            ChatMessage(
                id=uuid.uuid4(),
                session_id=sid,
                role="assistant",
                content="好的",
                status="done",
            )
        )
        sess.commit()
    _patch_db(monkeypatch, Session)

    mock_llm = MagicMock()
    mock_llm.chat.side_effect = RuntimeError("LLM down")

    from app.tasks.title_generation import generate_session_title

    with patch("app.tasks.title_generation.get_llm_service", return_value=mock_llm):
        generate_session_title(str(sid))
    with Session() as sess:
        s = sess.query(ChatSession).filter_by(id=sid).one()
        # short content (≤20 chars) → no ellipsis appended
        assert s.title == short_content
        assert "..." not in s.title
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
