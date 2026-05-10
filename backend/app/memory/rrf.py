"""RRF v2 — 时间感知 + importance 加权 reciprocal rank fusion.

算法深度补丁 #3 完整实现.

公式 (spec § 11 末尾 #3):
    score_final = (Σ 1/(k + rank_in_retriever)) × importance_weight × time_decay
    importance_weight ∈ {0.6, 0.75, 0.95}  (三档, low 不被完全压制)
    time_decay = DECAY_FLOOR + (1 - DECAY_FLOOR) × exp(-Δt / τ)
    τ_days ∈ {365 (HOLDS/SOLD), 180 (PREFERS/AVOIDS/WATCHES), 90 (EXPRESSED_VIEW/STUDIED)}

历史 edge (valid_to IS NOT NULL) 用 valid_to 作衰减参考点 — 事实"最近一次为真的时间"
是更准确的 freshness 锚点.

契约: docs/superpowers/plans/2026-05-11-c5-plan-shared-contracts.md § 5
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

# 契约 § 5: 常量必须严守, Plan 8 eval pipeline 引用同名常量做覆盖率检查
IMPORTANCE_WEIGHT_MAP: dict[float, float] = {
    0.9: 0.95,
    0.5: 0.75,
    0.2: 0.6,
}
"""importance 三档映射. low(0.2) 不完全压制(下限 0.6), 保长尾召回."""

TAU_DAYS_BY_REL_TYPE: dict[str, int] = {
    "HOLDS": 365,
    "SOLD": 365,
    "PREFERS": 180,
    "AVOIDS": 180,
    "WATCHES": 180,
    "EXPRESSED_VIEW": 90,
    "STUDIED": 90,
}
"""τ 按 rel_type 分级 — 金融垂直洞察: 持仓事实(365d) > 偏好(180d) > 观点(90d)."""

TAU_DAYS_DEFAULT: int = 180
"""未在 map 中的 rel_type 走 fallback, 如 BELONGS_TO / HAS_CONCEPT / CORRELATED_WITH."""

DECAY_FLOOR: float = 0.5
"""时间衰减底 — 老 fact 不消失, 保 audit 价值与长尾召回."""

RRF_K: int = 60
"""RRF 公式标准常量 (Cormack et al. 2009)."""

_IMPORTANCE_FALLBACK: float = 0.75
"""importance 不是三档之一(老数据 / 抽取异常)走中档 fallback."""


def _compute_importance_weight(importance: float | None) -> float:
    """importance 三档映射 + fallback. 私有 helper."""
    if importance is None:
        return _IMPORTANCE_FALLBACK
    return IMPORTANCE_WEIGHT_MAP.get(importance, _IMPORTANCE_FALLBACK)


def compute_time_decay(
    rel_type: str,
    valid_from: datetime,
    valid_to: datetime | None,
    *,
    _now: datetime | None = None,
) -> float:
    """time_decay = DECAY_FLOOR + (1 - DECAY_FLOOR) × exp(-Δt / τ).

    历史 edge (valid_to is not None) 用 valid_to 作衰减参考点 — 事实"最近一次为真的
    时间"作 freshness 锚点比"开始为真"更准.

    Args:
        rel_type: 11 类 REL_TYPES 之一(契约 registry).
        valid_from: edge.valid_from(必填).
        valid_to: edge.valid_to(可选, 历史 edge 才有).
        _now: test injection, 生产用 None → datetime.now(UTC).

    Returns:
        decay ∈ [DECAY_FLOOR, 1.0].
    """
    now = _now if _now is not None else datetime.now(UTC)
    # 历史 edge 用 valid_to, 当前 edge 用 valid_from
    ref_time = valid_to if valid_to is not None else valid_from
    # 防御: tz-naive 时刻补 UTC
    if ref_time.tzinfo is None:
        ref_time = ref_time.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    delta_days = max((now - ref_time).total_seconds() / 86400.0, 0.0)
    tau_days = TAU_DAYS_BY_REL_TYPE.get(rel_type, TAU_DAYS_DEFAULT)
    return DECAY_FLOOR + (1.0 - DECAY_FLOOR) * math.exp(-delta_days / tau_days)


def reciprocal_rank_fusion_v2(
    retriever_results: list[list[dict[str, Any]]],
    edges_meta: dict[str, dict[str, Any]],
    k: int = RRF_K,
    top: int = 5,
    *,
    _now: datetime | None = None,
) -> list[dict[str, Any]]:
    """spec § 11 末尾 #3 时间感知 RRF v2.

    Args:
        retriever_results: 各 retriever 已排序的 result list, 每个 item 必须含 'edge_id'.
        edges_meta: edge_id → {rel_type, importance, valid_from, valid_to} 的查询字典,
                    由 retriever.format_edges_meta_for_rrf 构造.
        k: RRF 常数, 默认 60.
        top: 返回 top-K, 默认 5.
        _now: test injection.

    Returns:
        list of {edge_id, score} 按 final score 降序, 长度 ≤ top.

    Raises:
        KeyError: 若 retriever_results 中某 edge_id 不在 edges_meta — 调用方必须保证一致.
    """
    rrf_scores: dict[str, float] = defaultdict(float)
    for retr_list in retriever_results:
        for rank, item in enumerate(retr_list, start=1):
            rrf_scores[str(item["edge_id"])] += 1.0 / (k + rank)

    final_scores: dict[str, float] = {}
    for eid, base in rrf_scores.items():
        meta = edges_meta[eid]
        imp_weight = _compute_importance_weight(meta.get("importance"))
        time_decay = compute_time_decay(
            rel_type=meta["rel_type"],
            valid_from=meta["valid_from"],
            valid_to=meta.get("valid_to"),
            _now=_now,
        )
        final_scores[eid] = base * imp_weight * time_decay

    sorted_eids = sorted(final_scores.keys(), key=lambda x: -final_scores[x])
    return [{"edge_id": eid, "score": final_scores[eid]} for eid in sorted_eids[:top]]
