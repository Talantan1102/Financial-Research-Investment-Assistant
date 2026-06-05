"""AGE 同步必须真 best-effort:cypher 失败不得毒死外层 PG 事务。

对话流评估冒烟发现(2026-06-05 #4):本地 PG 无 AGE 扩展时,
archival_memory_insert 里的 age_merge_node 失败被 try/except 捕获,
但 PG 事务已 aborted——后续边 INSERT 全灭于 InFailedSqlTransaction,
"best-effort"名存实亡。修法:AGE 语句跑在 SAVEPOINT 里。

本测试在无 AGE 扩展的测试 PG 上天然成立;若测试库装了 AGE,
merge 会成功,断言"事务仍健康"同样成立(两种环境都有效)。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from app.memory.age_sync import age_merge_node
from sqlalchemy import text


@pytest.fixture
def pg_session(pg_memory_session_factory: Callable[[], Any]):
    s = pg_memory_session_factory()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def _age_available(session: Any) -> bool:
    try:
        with session.begin_nested():
            session.execute(text("SELECT 1 FROM ag_catalog.ag_graph LIMIT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False


def test_age_failure_does_not_poison_outer_transaction(pg_session: Any) -> None:
    # 在同一事务里先做一个正常写入,模拟 archival_memory_insert 的事务上下文
    pg_session.execute(text("SELECT 1"))
    try:
        age_merge_node(session=pg_session, node_id=uuid4(), entity_type="User")
    except Exception:  # noqa: BLE001
        pass  # AGE 不可用时预期抛;关键是下面外层事务必须仍可用
    # 外层事务必须没被毒死:任何后续语句都应正常执行
    row = pg_session.execute(text("SELECT 42")).scalar()
    assert row == 42, "AGE 失败毒死了外层事务(InFailedSqlTransaction)"


async def test_archival_insert_succeeds_without_age(
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """冒烟发现 #5:生产库无 AGE 扩展,边镜像若坚持原子语义则所有写入永远失败。
    修复后:AGE 边镜像降级为 best-effort(与节点镜像、Milvus outbox 同哲学),
    PG 仍是 SSOT,无 AGE 环境下 insert 必须成功。"""
    from datetime import UTC, datetime

    from app.memory.hierarchical import HierarchicalMemory

    s = pg_memory_session_factory()
    user_id, sess_id = uuid4(), uuid4()
    s.execute(
        text(
            'INSERT INTO users (id, username, email, hashed_password, is_active) '
            'VALUES (:i, :u, :e, :p, true)'
        ),
        {'i': str(user_id), 'u': f'age5-{user_id.hex[:8]}',
         'e': f'age5-{user_id.hex[:8]}@t.local', 'p': 'x'},
    )
    s.execute(
        text('INSERT INTO chat_sessions (id, user_id, title) VALUES (:s, :u, :t)'),
        {'s': str(sess_id), 'u': str(user_id), 't': 'age5'},
    )
    s.commit()
    from app.memory.models import ChatMemoryEpisode

    ep = ChatMemoryEpisode(
        user_id=user_id, session_id=sess_id, episode_index=1,
        user_message_text='白酒看多 就认提价权', agent_response_text='',
    )
    s.add(ep)
    s.commit()

    memory = HierarchicalMemory(
        pg_session_factory=pg_memory_session_factory,
        age_executor=None, milvus_client=None, embed_service=None,
        llm_extractor=None, llm_judge=None,
    )
    edge = await memory.archival_memory_insert(
        user_id=user_id,
        content={
            'rel_type': 'EXPRESSED_VIEW',
            'source_entity_type': 'User', 'source_label': 'User',
            'target_entity_type': 'Industry', 'target_label': '白酒',
            'valid_from': datetime(2025, 1, 6, tzinfo=UTC), 'valid_to': None,
            'properties': {'stance': '看多'},
        },
        reasoning='test', importance=0.9,
        evidence_quote='白酒看多 就认提价权',
        episode_id=ep.episode_id,
    )
    assert edge is not None, '无 AGE 环境下 insert 不得失败(边镜像应降级)'
    s.close()
