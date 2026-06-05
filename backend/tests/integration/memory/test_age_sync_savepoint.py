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
