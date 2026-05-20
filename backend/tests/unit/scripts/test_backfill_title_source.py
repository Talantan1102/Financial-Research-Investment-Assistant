"""Backfill script: 已有非默认 title 的老 session 一次性置为 llm_generated."""

from __future__ import annotations

import uuid

import pytest
from app.models.chat import ChatSession
from app.scripts.backfill_title_source import backfill
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def engine_with_seed():
    engine = create_engine("sqlite:///:memory:")
    ChatSession.__table__.create(bind=engine)
    Session = sessionmaker(bind=engine)
    with Session() as sess:
        sess.add(ChatSession(id=uuid.uuid4(), title="贵州茅台估值..."))  # 已有 title
        sess.add(ChatSession(id=uuid.uuid4(), title="新对话"))  # 还没被聊过
        sess.add(
            ChatSession(id=uuid.uuid4(), title="美的家电分析", title_source="user_renamed")
        )  # 用户已手动改名 — 不动
        sess.commit()
    return engine


def test_backfill_marks_non_default_titles_as_llm_generated(engine_with_seed):
    n = backfill(engine_with_seed)
    assert n == 1  # 只有一行被更新
    Session = sessionmaker(bind=engine_with_seed)
    with Session() as sess:
        rows = sess.query(ChatSession).all()
        by_title = {r.title: r.title_source for r in rows}
        assert by_title["贵州茅台估值..."] == "llm_generated"
        assert by_title["新对话"] == "pending"
        assert by_title["美的家电分析"] == "user_renamed"  # 未被覆盖


def test_backfill_is_idempotent(engine_with_seed):
    n1 = backfill(engine_with_seed)
    n2 = backfill(engine_with_seed)
    assert n1 == 1
    assert n2 == 0  # 第二次跑没有再更新任何行
