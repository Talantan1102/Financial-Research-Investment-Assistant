"""数据库断言引擎:直接往真 PG 种节点/边,验证各断言类型的红绿判定。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from app.memory.models import ChatMemoryEdge, ChatMemoryEpisode, ChatMemoryNode
from eval.memory_dialogue.db_assertions import DbAssertionEngine
from eval.memory_dialogue.script_schema import DbCheck
from sqlalchemy import text


def _utc(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


@pytest.fixture
def seeded_user(pg_memory_session_factory: Callable[[], Any]):
    """种一个用户 + '白酒'目标节点 + 一条看多旧边(已结束)+ 一条两年版新边(active)。"""
    session = pg_memory_session_factory()
    user_id = uuid4()
    session.execute(
        text(
            "INSERT INTO users (id, username, email, hashed_password, is_active) "
            "VALUES (:i, :u, :e, :p, true)"
        ),
        {
            "i": str(user_id),
            "u": f"eval-{user_id.hex[:8]}",
            "e": f"eval-{user_id.hex[:8]}@test.local",
            "p": "x",
        },
    )
    chat_session_id = uuid4()
    session.execute(
        text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:id, :uid, :title)"),
        {"id": str(chat_session_id), "uid": str(user_id), "title": "eval-db-assertions"},
    )
    src = ChatMemoryNode(user_id=user_id, entity_type="User", entity_label="User")
    tgt = ChatMemoryNode(user_id=user_id, entity_type="Industry", entity_label="白酒")
    session.add_all([src, tgt])
    session.flush()
    ep = ChatMemoryEpisode(
        user_id=user_id, session_id=chat_session_id, episode_index=1,
        user_message_text="白酒我看多 就认提价权", agent_response_text="(记录观点)",
    )
    session.add(ep)
    session.flush()
    old = ChatMemoryEdge(
        user_id=user_id, source_node_id=src.node_id, target_node_id=tgt.node_id,
        rel_type="EXPRESSED_VIEW", valid_from=_utc("2025-01-06"), valid_to=_utc("2025-02-03"),
        importance=0.9, properties={"stance": "看多", "horizon": "三年", "logic": "提价权"},
        source_episode_id=ep.episode_id,
    )
    new = ChatMemoryEdge(
        user_id=user_id, source_node_id=src.node_id, target_node_id=tgt.node_id,
        rel_type="EXPRESSED_VIEW", valid_from=_utc("2025-02-03"), valid_to=None,
        importance=0.9, properties={"stance": "看多", "horizon": "两年", "logic": "提价权"},
        source_episode_id=ep.episode_id,
    )
    session.add_all([old, new])
    session.commit()
    try:
        yield user_id, session
    finally:
        session.close()


def test_fact_active_green(seeded_user) -> None:
    user_id, session = seeded_user
    engine = DbAssertionEngine(session=session, user_id=user_id)
    r = engine.run_check(DbCheck(
        type="fact_active",
        params={"rel_type": "EXPRESSED_VIEW", "target_label": "白酒", "value_contains": ["看多", "两年"]},
    ))
    assert r.passed, r.detail


def test_fact_active_red_when_value_missing(seeded_user) -> None:
    user_id, session = seeded_user
    engine = DbAssertionEngine(session=session, user_id=user_id)
    r = engine.run_check(DbCheck(
        type="fact_active",
        params={"rel_type": "EXPRESSED_VIEW", "target_label": "白酒", "value_contains": ["中性"]},
    ))
    assert not r.passed
    assert "中性" in r.detail


def test_old_invalidated_green(seeded_user) -> None:
    user_id, session = seeded_user
    engine = DbAssertionEngine(session=session, user_id=user_id)
    r = engine.run_check(DbCheck(
        type="old_invalidated",
        params={"rel_type": "EXPRESSED_VIEW", "target_label": "白酒", "min_count": 1},
    ))
    assert r.passed, r.detail


def test_fact_count_snapshot_no_increase(seeded_user) -> None:
    user_id, session = seeded_user
    engine = DbAssertionEngine(session=session, user_id=user_id)
    engine.snapshot_counts(rel_type="EXPRESSED_VIEW", target_label="白酒")
    r = engine.run_check(DbCheck(
        type="fact_count_no_increase",
        params={"rel_type": "EXPRESSED_VIEW", "target_label": "白酒"},
    ))
    assert r.passed, r.detail


def test_fact_count_no_increase_without_snapshot_is_red(seeded_user) -> None:
    user_id, session = seeded_user
    engine = DbAssertionEngine(session=session, user_id=user_id)
    r = engine.run_check(DbCheck(
        type="fact_count_no_increase",
        params={"rel_type": "EXPRESSED_VIEW", "target_label": "白酒"},
    ))
    assert not r.passed
    assert "基线" in r.detail or "snapshot" in r.detail


def test_invalidated_chain_intact(seeded_user) -> None:
    user_id, session = seeded_user
    engine = DbAssertionEngine(session=session, user_id=user_id)
    ok = engine.run_check(DbCheck(
        type="invalidated_chain_intact",
        params={"rel_type": "EXPRESSED_VIEW", "target_label": "白酒", "expected_versions": 2},
    ))
    assert ok.passed, ok.detail
    too_many = engine.run_check(DbCheck(
        type="invalidated_chain_intact",
        params={"rel_type": "EXPRESSED_VIEW", "target_label": "白酒", "expected_versions": 3},
    ))
    assert not too_many.passed


def test_valid_from_is_event_time(seeded_user) -> None:
    user_id, session = seeded_user
    engine = DbAssertionEngine(session=session, user_id=user_id)
    ok = engine.run_check(DbCheck(
        type="valid_from_is_event_time",
        params={"rel_type": "EXPRESSED_VIEW", "target_label": "白酒", "expected_date": "2025-02-03"},
    ))
    assert ok.passed, ok.detail
    wrong = engine.run_check(DbCheck(
        type="valid_from_is_event_time",
        params={"rel_type": "EXPRESSED_VIEW", "target_label": "白酒", "expected_date": "2025-06-05"},
    ))
    assert not wrong.passed
    assert "录入时间" in wrong.detail


def test_no_fact_written(seeded_user) -> None:
    """持仓仲裁:不得出现 HOLDS 持仓边(种的是观点边,应绿)。"""
    user_id, session = seeded_user
    engine = DbAssertionEngine(session=session, user_id=user_id)
    r = engine.run_check(DbCheck(type="no_fact_written", params={"rel_type": "HOLDS"}))
    assert r.passed, r.detail


def test_unknown_check_type_is_red_not_raise(seeded_user) -> None:
    user_id, session = seeded_user
    engine = DbAssertionEngine(session=session, user_id=user_id)
    r = engine.run_check(DbCheck(type="does_not_exist", params={}))
    assert not r.passed
    assert "未知断言类型" in r.detail
