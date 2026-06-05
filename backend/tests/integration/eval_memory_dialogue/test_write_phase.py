"""写阶段:episodes 按脚本日期入库 → 假抽取器写边 → 逐 session 断言红绿。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.memory.models import ChatMemoryEdge, ChatMemoryNode
from eval.memory_dialogue.script_schema import ScriptSession, load_script
from eval.memory_dialogue.write_phase import WritePhaseRunner
from sqlalchemy import text


@pytest.fixture
def fresh_user(pg_memory_session_factory: Callable[[], Any]):
    session = pg_memory_session_factory()
    user_id, chat_session_id = uuid4(), uuid4()
    session.execute(
        text(
            "INSERT INTO users (id, username, email, hashed_password, is_active) "
            "VALUES (:i, :u, :e, :p, true)"
        ),
        {
            "i": str(user_id),
            "u": f"wp-{user_id.hex[:8]}",
            "e": f"wp-{user_id.hex[:8]}@test.local",
            "p": "x",
        },
    )
    session.execute(
        text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:s, :u, :t)"),
        {"s": str(chat_session_id), "u": str(user_id), "t": "eval-write-phase"},
    )
    session.commit()
    try:
        yield user_id, chat_session_id, session
    finally:
        session.close()


def _fake_extractor(session_handle: Any):
    """假抽取器:第 1 个 session 写一条看多边;后续 session 把 active 边全部盖 valid_to。"""

    async def extract(user_id: UUID, chat_session_id: UUID, ss: ScriptSession) -> None:
        s = session_handle
        ep_row = s.execute(
            text(
                "SELECT episode_id FROM chat_memory_episodes "
                "WHERE user_id=:u ORDER BY episode_index LIMIT 1"
            ),
            {"u": str(user_id)},
        ).first()
        assert ep_row is not None, "write_phase 应先插 episode 再调抽取器"
        if ss.n == 1:
            src = ChatMemoryNode(user_id=user_id, entity_type="User", entity_label="User")
            tgt = ChatMemoryNode(user_id=user_id, entity_type="Industry", entity_label="白酒")
            s.add_all([src, tgt])
            s.flush()
            s.add(ChatMemoryEdge(
                user_id=user_id, source_node_id=src.node_id, target_node_id=tgt.node_id,
                rel_type="EXPRESSED_VIEW",
                valid_from=datetime.combine(ss.date, datetime.min.time(), tzinfo=UTC),
                valid_to=None, importance=0.9, properties={"stance": "看多"},
                source_episode_id=ep_row[0],
            ))
        else:
            for e in s.query(ChatMemoryEdge).filter_by(user_id=user_id, valid_to=None):
                e.valid_to = datetime.combine(ss.date, datetime.min.time(), tzinfo=UTC)
        s.commit()

    return extract


_SCRIPT_GREEN = """
script_id: write-minimal
title: "写阶段最小脚本"
family: 观点演化族
substrate: 观点演化
sessions:
  - n: 1
    date: 2025-01-06
    length: 短
    turns: [{u: "白酒看多"}, {a: "(回应)"}]
  - n: 2
    date: 2025-04-01
    length: 短
    turns: [{u: "白酒观点收回"}, {a: "(回应)"}]
db_assertions:
  - after: 1
    assert:
      - {type: fact_active, rel_type: EXPRESSED_VIEW, target_label: 白酒, value_contains: ["看多"]}
  - after: 2
    assert:
      - {type: old_invalidated, rel_type: EXPRESSED_VIEW, target_label: 白酒, min_count: 1}
probes:
  - {tier: 直球, dimension: 知识更新, q: "占位", expect_contain: [], expect_not: [], judge_rubric: "占位"}
"""

_SCRIPT_RED = """
script_id: write-red
title: "红灯脚本"
family: 观点演化族
substrate: 观点演化
sessions:
  - n: 1
    date: 2025-01-06
    length: 短
    turns: [{u: "白酒看多"}, {a: "(回应)"}]
db_assertions:
  - after: 1
    assert:
      - {type: fact_active, rel_type: EXPRESSED_VIEW, target_label: 白酒, value_contains: ["中性"]}
probes:
  - {tier: 直球, dimension: 知识更新, q: "占位", expect_contain: [], expect_not: [], judge_rubric: "占位"}
"""


async def test_write_phase_runs_assertions_per_session(fresh_user, tmp_path: Path) -> None:
    user_id, chat_session_id, session = fresh_user
    p = tmp_path / "s.yaml"
    p.write_text(_SCRIPT_GREEN, encoding="utf-8")
    script = load_script(p)
    runner = WritePhaseRunner(
        session=session, user_id=user_id, chat_session_id=chat_session_id,
        extract_session=_fake_extractor(session),
    )
    report = await runner.run(script)
    assert report.all_passed, [r.detail for r in report.results if not r.passed]
    # episode created_at 必须等于脚本日期,不是今天
    row = session.execute(
        text(
            "SELECT created_at FROM chat_memory_episodes "
            "WHERE user_id=:u ORDER BY episode_index LIMIT 1"
        ),
        {"u": str(user_id)},
    ).first()
    assert row is not None and str(row[0]).startswith("2025-01-06")


async def test_write_phase_collects_red_not_raises(fresh_user, tmp_path: Path) -> None:
    """断言失败收集成红灯报告,不抛异常中断后续 session。"""
    user_id, chat_session_id, session = fresh_user
    p = tmp_path / "s.yaml"
    p.write_text(_SCRIPT_RED, encoding="utf-8")
    runner = WritePhaseRunner(
        session=session, user_id=user_id, chat_session_id=chat_session_id,
        extract_session=_fake_extractor(session),
    )
    report = await runner.run(load_script(p))
    assert not report.all_passed
    assert any("中性" in r.detail for r in report.results)
