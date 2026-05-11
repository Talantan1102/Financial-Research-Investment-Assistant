"""长尾召回监控 (eval pipeline 接入层) — spec § 11 末尾 #3 收束.

Plan 3 ship `backend/app/memory/long_tail_monitor.py` (compute_long_tail_metrics
on retrieval log rows). Plan 8 ship 本 module 提供 eval-runner-friendly API:
    - long_tail_recall_check(sample_results, p90_floor_days) — 直接 over retrieved facts
    - weekly_report_sql() — 周报 SQL string

接受 eval_runner 调用入口的 sample_results 形态:
    [
        {"query": str, "top5_facts": [{"valid_from": datetime, ...}, ...]},
        ...
    ]

acceptance(spec § 11 #3):
    sample 100 query, top-5 valid_from P90 不能全集中近 7 天.
    P90 query 至少有一条 fact valid_from 距今 ≥ 7 天.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def long_tail_recall_check(
    sample_results: list[dict[str, Any]],
    p90_floor_days: int = 7,
) -> dict[str, Any]:
    """计算长尾召回 P90 指标.

    每个 query 取 top-5 facts 中"最老"那条 fact 的 age (max age in days);
    所有 query 的 max-age 升序排, 取 bottom-10% 处的值作 P90 (90% 的 query
    的 oldest-fact 都比这老). 该 P90 < floor → violated.

    Args:
        sample_results: list of {"query": str, "top5_facts": list[fact dict]}.
            fact dict 要求至少有 valid_from (datetime | iso string).
        p90_floor_days: 最低 P90 阈值, 默认 7 天.

    Returns:
        {"violated": bool, "p90_min_age_days": int, "p90_floor_days": int,
         "samples": int, "reason"?: str}
    """
    now = datetime.now(UTC)
    min_age_days_per_query = []
    for sr in sample_results:
        ages = []
        for fact in sr.get("top5_facts", []):
            vf = fact.get("valid_from")
            if vf is None:
                continue
            if isinstance(vf, str):
                vf = datetime.fromisoformat(vf)
            if vf.tzinfo is None:
                vf = vf.replace(tzinfo=UTC)
            ages.append((now - vf).days)
        if ages:
            # 该 query 中"最老"那条 fact 的年龄
            min_age_days_per_query.append(max(ages))

    if not min_age_days_per_query:
        return {
            "violated": True,
            "p90_min_age_days": 0,
            "p90_floor_days": p90_floor_days,
            "samples": 0,
            "reason": "no samples",
        }

    min_age_days_per_query.sort()
    # P90 = bottom 10% (90% of queries are at least this old)
    p90_idx = max(0, int(len(min_age_days_per_query) * 0.1))
    p90 = min_age_days_per_query[p90_idx]
    return {
        "violated": p90 < p90_floor_days,
        "p90_min_age_days": p90,
        "p90_floor_days": p90_floor_days,
        "samples": len(sample_results),
    }


def weekly_report_sql() -> str:
    """周报 SQL — 跑近 7 天 retrieval 命中 fact 的 valid_from 分布."""
    return """
    -- 长尾召回监控周报: 最近 7 天 retrieval 命中 fact 的 valid_from 分布
    SELECT
      DATE_TRUNC('day', l.created_at) AS bucket_day,
      COUNT(*) AS retrieval_count,
      AVG(l.top_k_valid_from_p90_days) AS avg_p90_age_days,
      PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY l.top_k_valid_from_p90_days)
          AS p50_age_days,
      PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY l.top_k_valid_from_p90_days)
          AS p90_age_days
    FROM chat_memory_retrieval_logs l
    WHERE l.created_at > NOW() - INTERVAL '7 day'
    GROUP BY bucket_day
    ORDER BY bucket_day DESC;
    """
