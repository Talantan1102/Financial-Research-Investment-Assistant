"""BM25 中文召回:建边时填 search_tokens(jieba),search_vector 非空,中文 query 能召回。

对话流评估读侧全红根因之一:archival_memory_insert 建边没填 search_tokens →
search_vector(GENERATED)为空 → BM25 @@ 永不匹配 → 中文零召回。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Callable

import pytest
from app.memory.conflict_resolver import ConflictAction, ConflictVerdict, apply_action
from app.memory.models import ChatMemoryNode
from app.memory.registry import jieba_tokenize_for_search
from app.memory.retriever import bm25_search
from sqlalchemy import text


@pytest.fixture
def user_with_session(pg_memory_session_factory: Callable[[], Any]):
    s = pg_memory_session_factory()
    uid = uuid.uuid4()
    s.execute(text("INSERT INTO users (id, username, email, hashed_password, is_active) VALUES (:i,:u,:e,:p,true)"),
              {"i": str(uid), "u": f"bm-{uid.hex[:8]}", "e": f"bm-{uid.hex[:8]}@t.local", "p": "x"})
    sid = uuid.uuid4()
    s.execute(text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:s,:u,'bm')"), {"s": str(sid), "u": str(uid)})
    from app.memory.models import ChatMemoryEpisode
    ep = ChatMemoryEpisode(user_id=uid, session_id=sid, episode_index=1, user_message_text="白酒看多")
    s.add(ep); s.flush()
    yield uid, s, ep.episode_id
    s.rollback(); s.close()


def test_bm25_recalls_chinese_after_search_tokens(user_with_session) -> None:
    uid, s, ep_id = user_with_session
    src = ChatMemoryNode(user_id=uid, entity_type="User", entity_label="User")
    tgt = ChatMemoryNode(user_id=uid, entity_type="Industry", entity_label="白酒")
    s.add_all([src, tgt]); s.flush()
    apply_action(
        s, ConflictVerdict(action=ConflictAction.APPEND_NEW, reasoning="独立"), [],
        user_id=uid, source_node_id=src.node_id, target_node_id=tgt.node_id,
        rel_type="EXPRESSED_VIEW", valid_from=datetime(2025, 1, 6, tzinfo=UTC), valid_to=None,
        source_episode_id=ep_id, importance=0.9, reasoning="用户看多白酒",
        properties={"stance": "看多"},
        search_tokens=jieba_tokenize_for_search("EXPRESSED_VIEW 白酒 用户看多白酒 看多"),
    )
    s.commit()
    hits = bm25_search(s, user_id=uid, query="白酒", k=5)
    assert hits, "中文 query '白酒' 应召回该边(search_tokens 填了 jieba 切词)"
