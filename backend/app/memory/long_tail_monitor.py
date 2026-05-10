"""长尾召回监控 — 算法深度补丁 #3 验证.

spec § 11 #3 acceptance:
    "eval pipeline sample 100 query, top-5 valid_from P90 不能全集中近 7 天 →
     长尾召回监控周报上大盘".

Plan 3 提供 instrumentation, Plan 8 eval pipeline 调本 module 计算大盘指标.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

LONG_TAIL_P90_THRESHOLD_DAYS: int = 7


@dataclass
class LongTailReport:
    sample_count: int
    median_p90_days: float
    alert: bool  # P90 sample 中位数 < 阈值 → True
    samples_below_threshold_pct: float  # 落入阈值内的占比
    note: str = ""

    @property
    def passing(self) -> bool:
        return not self.alert


def compute_long_tail_metrics(
    sample_logs: list[dict[str, Any]],
    threshold_days: int = LONG_TAIL_P90_THRESHOLD_DAYS,
) -> LongTailReport:
    """从 retrieval_logs 行采样计算长尾召回指标.

    Args:
        sample_logs: 通常是 chat_memory_retrieval_logs 最近 N 行,
            每行至少含 'top_k_valid_from_p90_days' float field.
        threshold_days: 长尾告警阈值, 默认 7 天.

    Returns:
        LongTailReport.
    """
    valid = [
        r["top_k_valid_from_p90_days"]
        for r in sample_logs
        if r.get("top_k_valid_from_p90_days") is not None
    ]
    if not valid:
        return LongTailReport(
            sample_count=0,
            median_p90_days=0.0,
            alert=False,
            samples_below_threshold_pct=0.0,
            note="empty sample",
        )
    median_p90 = statistics.median(valid)
    below = [x for x in valid if x < threshold_days]
    pct_below = len(below) / len(valid)
    alert = median_p90 < threshold_days
    return LongTailReport(
        sample_count=len(valid),
        median_p90_days=float(median_p90),
        alert=alert,
        samples_below_threshold_pct=pct_below,
        note=("alert: median P90 < threshold" if alert else "ok"),
    )


def fetch_recent_retrieval_logs(
    session: Session,
    n_samples: int = 100,
) -> list[dict[str, Any]]:
    """Plan 8 eval pipeline 调用入口 — 从 PG 拉最近 N 条 retrieval_logs."""
    rows = session.execute(
        text(
            """
            SELECT log_id, user_id, query_text,
                   top_k_valid_from_p90_days, retriever_breakdown, latency_ms, created_at
            FROM chat_memory_retrieval_logs
            ORDER BY created_at DESC
            LIMIT :n
            """
        ),
        {"n": n_samples},
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        if hasattr(r, "_mapping"):
            out.append(dict(r._mapping))
        elif isinstance(r, dict):
            out.append(dict(r))
        else:
            out.append(dict(r))
    return out
