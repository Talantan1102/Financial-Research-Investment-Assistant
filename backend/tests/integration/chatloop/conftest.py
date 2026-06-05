"""Integration fixtures for chatloop rebuild tests — 真 PG。

复用全局 conftest 的 pg_test_engine(drop+create_all 全 metadata,含新表
chat_session_context)与 pg_async_session_factory(async psycopg v3,真 commit
cycle,无 rollback isolation——async tests 需要跨 async_with 看到写入)。

LLM_MODE 强制 mock(继承 tests/integration/conftest.py)。rebuild 的压缩走
注入的 Fake LLM,不碰真模型。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text


@pytest.fixture(autouse=True)
def _ensure_chatloop_schema(pg_test_engine: Engine) -> Iterator[None]:
    """确保 chat_session_context 表存在(pg_test_engine 已 create_all 全 metadata)。

    pg_async_session_factory 仅依赖 pg_test_container,不触发 create_all;显式
    pull pg_test_engine 让 session-scoped 建表先跑,新表 chat_session_context
    随 Base.metadata.create_all 一并建出。
    """
    # pg_test_engine fixture body 已跑过 create_all;此处只做存在性 sanity。
    with pg_test_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT to_regclass('public.chat_session_context')")
        ).scalar()
    assert exists == "chat_session_context", (
        "chat_session_context 表未建出 — 检查 app.models 是否 export ChatSessionContext"
    )
    yield
