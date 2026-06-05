"""AGE Cypher sync helper — write graph mirror in same PG transaction.

spec § 4 Step 7: PG INSERT chat_memory_edges + AGE Cypher CREATE 必须 atomic.
AGE 失败 → 整事务 rollback (失败处理矩阵 spec § 4 末尾).

2026-06-05 对话流评估冒烟发现 #4:调用方(hierarchical)按"best-effort"语义
catch 本模块抛出的异常继续往下走,但 cypher 语句失败已使 PG 事务 aborted,
后续 INSERT 全灭于 InFailedSqlTransaction——catch Python 异常救不了 PG 事务。
修法:AGE 语句一律跑在 SAVEPOINT(begin_nested)里,失败回滚到保存点后再
raise(保持原 raise 契约),外层事务始终健康;无 AGE 扩展的环境因此可用。
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.memory.registry import REL_TYPES, is_valid_rel_type

_logger = logging.getLogger(__name__)


def age_create_edge(
    session: Session,
    *,
    edge_id: UUID,
    source_node_id: UUID,
    target_node_id: UUID,
    rel_type: str,
) -> None:
    """Create AGE edge mirroring PG chat_memory_edges row.

    Cypher: MATCH (s {{node_id: <src>}}), (t {{node_id: <tgt>}})
            CREATE (s)-[r:<rel_type> {{edge_id: <eid>}}]->(t)

    Caller must:
    1. Already INSERT'd chat_memory_nodes (so AGE has Cypher node mirror; the
       hierarchical.archival_memory_insert path uses MERGE to ensure node
       presence).
    2. Already INSERT'd chat_memory_edges row.
    3. Manage transaction (commit/rollback).

    Raises if rel_type not in REL_TYPES whitelist (defense-in-depth, prompt
    output 应已 reject by ExtractedEdge validator) or AGE Cypher fails.
    """
    if not is_valid_rel_type(rel_type):
        raise ValueError(f"rel_type {rel_type!r} not in {REL_TYPES}")

    # rel_type 安全: 已 whitelist 校验, 直接 string interpolation OK
    # node_id 通过 Cypher 字符串插值 (AGE 不支持 ? param 在 Cypher 内, 改用安全字符串)
    cypher = f"""
        SELECT * FROM cypher('chat_memory', $$
            MATCH (s), (t)
            WHERE s.node_id = '{source_node_id}' AND t.node_id = '{target_node_id}'
            CREATE (s)-[r:{rel_type} {{edge_id: '{edge_id}'}}]->(t)
            RETURN r
        $$) AS (r agtype)
    """
    try:
        with session.begin_nested():  # SAVEPOINT: 失败不毒外层事务
            session.execute(text(cypher))
    except Exception as exc:
        _logger.error(
            "AGE Cypher CREATE edge failed (edge_id=%s rel=%s): %s",
            edge_id,
            rel_type,
            exc,
        )
        raise


def age_merge_node(
    session: Session,
    *,
    node_id: UUID,
    entity_type: str,
) -> None:
    """Idempotent MERGE node into AGE 'chat_memory' graph.

    spec § 4 Step 7: Plan 1B 没在 PG INSERT chat_memory_nodes 时同步 AGE,
    所以 archival_memory_insert pipeline 在 get_or_create node 后调用此 helper
    保证 AGE node 存在(MERGE 幂等). entity_type 必须在 7 vlabel 内.

    Caller must already INSERT chat_memory_nodes row in PG.
    """
    from app.memory.registry import ENTITY_TYPES

    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"entity_type {entity_type!r} not in {ENTITY_TYPES}")

    cypher = f"""
        SELECT * FROM cypher('chat_memory', $$
            MERGE (n:{entity_type} {{node_id: '{node_id}'}})
            RETURN n
        $$) AS (n agtype)
    """
    try:
        with session.begin_nested():  # SAVEPOINT: 失败不毒外层事务
            session.execute(text(cypher))
    except Exception as exc:
        _logger.error(
            "AGE Cypher MERGE node failed (node_id=%s type=%s): %s",
            node_id,
            entity_type,
            exc,
        )
        raise
