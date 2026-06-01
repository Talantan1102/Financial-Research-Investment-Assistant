"""Plan 3 instrumentation — 长尾召回监控 + posterior calibration 数据落库.

调用方:
    - hierarchical.archival_memory_search → log_retrieval_hit (每次 search)
    - /memory router invalidate endpoint → log_user_reject (Plan 7)
    - Plan 5 posterior_calibration weekly job 消费两表

表名严守契约 § 17 A4:
    - chat_memory_retrieval_logs
    - chat_memory_retrieval_feedback

API 设计:
    - sync Session-based (跟 HierarchicalMemory 同 pattern)
    - 两个 helper 调用方: 一个传 session(在已开 transaction 内), 一个传 session_factory.
    - 测试时 monkey-patch 任意一个都易写.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _compute_p90_valid_from_age_days(
    edge_ids: list[str],
    edges_meta: dict[str, dict[str, Any]],
    now: datetime,
) -> float | None:
    """top-K edges valid_from 距 now 的天数 P90.

    返回 None 当 sample 为空.
    """
    ages: list[float] = []
    for eid in edge_ids:
        meta = edges_meta.get(eid)
        if not meta:
            continue
        vf = meta.get("valid_from")
        if vf is None:
            continue
        if vf.tzinfo is None:
            vf = vf.replace(tzinfo=UTC)
        ages.append((now - vf).total_seconds() / 86400.0)
    if not ages:
        return None
    sorted_ages = sorted(ages)
    # C49: use (n-1)*0.9 to avoid overshoot: n=10→idx8 (P90), n=100→idx89 (P90)
    idx = int((len(sorted_ages) - 1) * 0.9)
    idx = min(idx, len(sorted_ages) - 1)  # guard (no-op after fix, kept as safety)
    return sorted_ages[idx]


def log_retrieval_hit(
    session: Session,
    *,
    user_id: UUID,
    query_text: str,
    retrieved_edge_ids: list[str],
    rrf_scores: dict[str, float],
    edges_meta: dict[str, dict[str, Any]],
    retriever_breakdown: dict[str, int],
    latency_ms: int,
    _now: datetime | None = None,
) -> UUID:
    """Records 1 search hit for long-tail monitoring + posterior calibration.

    P90 valid_from age days 计算: 取 top-K edges 的 valid_from, 算 P90 距 now 天数.
    长尾召回告警阈值: P90 < 7 天 → 全集中近期, 触发 long_tail_monitor 告警.

    调用方在自己 transaction 内调本 helper, 自己 commit/rollback.
    """
    now = _now if _now is not None else datetime.now(UTC)
    log_id = uuid4()

    p90 = _compute_p90_valid_from_age_days(retrieved_edge_ids, edges_meta, now)

    session.execute(
        text(
            """
            INSERT INTO chat_memory_retrieval_logs
                (log_id, user_id, query_text, retrieved_edge_ids, rrf_scores,
                 top_k_valid_from_p90_days, retriever_breakdown, latency_ms, created_at)
            VALUES (:log_id, :user_id, :q, CAST(:eids AS JSONB), CAST(:scores AS JSONB),
                    :p90, CAST(:rb AS JSONB), :lat, :now)
            """
        ),
        {
            "log_id": str(log_id),
            "user_id": str(user_id),
            "q": query_text,
            "eids": _json_dumps(retrieved_edge_ids),
            "scores": _json_dumps(rrf_scores),
            "p90": p90,
            "rb": _json_dumps(retriever_breakdown),
            "lat": latency_ms,
            "now": now,
        },
    )
    return log_id


def log_user_reject(
    session: Session,
    *,
    user_id: UUID,
    edge_id: UUID,
    feedback_kind: str,  # 'reject' / 'confirm' / 'invalidate'
    reason: str | None = None,
    log_id: UUID | None = None,
) -> None:
    """Records 1 feedback signal. Plan 5 weekly job 消费做 posterior calibration."""
    if feedback_kind not in ("reject", "confirm", "invalidate"):
        raise ValueError(f"feedback_kind must be reject/confirm/invalidate, got {feedback_kind!r}")
    session.execute(
        text(
            """
            INSERT INTO chat_memory_retrieval_feedback
                (feedback_id, user_id, edge_id, feedback_kind, reason, log_id)
            VALUES (gen_random_uuid(), :uid, :eid, :kind, :reason, :log_id)
            """
        ),
        {
            "uid": str(user_id),
            "eid": str(edge_id),
            "kind": feedback_kind,
            "reason": reason,
            "log_id": str(log_id) if log_id else None,
        },
    )


def _json_dumps(value: Any) -> str:
    return json.dumps(value, default=str)
