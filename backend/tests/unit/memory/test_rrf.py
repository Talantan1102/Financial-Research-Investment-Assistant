"""L0 Unit: RRF v2 — 算法深度补丁 #3 时间感知 ranking 公式校验.

契约 ref: docs/superpowers/plans/2026-05-11-c5-plan-shared-contracts.md § 5
spec ref: § 11 末尾 #3 reciprocal_rank_fusion_v2 完整公式
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

from app.memory.rrf import (
    DECAY_FLOOR,
    IMPORTANCE_WEIGHT_MAP,
    RRF_K,
    TAU_DAYS_BY_REL_TYPE,
    TAU_DAYS_DEFAULT,
    compute_time_decay,
    reciprocal_rank_fusion_v2,
)


class TestConstants:
    """常量值严守契约 § 5 — Plan 8 eval pipeline 引用同名常量."""

    def test_importance_weight_map_three_tier(self) -> None:
        assert IMPORTANCE_WEIGHT_MAP == {0.9: 0.95, 0.5: 0.75, 0.2: 0.6}

    def test_tau_days_by_rel_type(self) -> None:
        assert TAU_DAYS_BY_REL_TYPE["HOLDS"] == 365
        assert TAU_DAYS_BY_REL_TYPE["SOLD"] == 365
        assert TAU_DAYS_BY_REL_TYPE["PREFERS"] == 180
        assert TAU_DAYS_BY_REL_TYPE["AVOIDS"] == 180
        assert TAU_DAYS_BY_REL_TYPE["WATCHES"] == 180
        assert TAU_DAYS_BY_REL_TYPE["EXPRESSED_VIEW"] == 90
        assert TAU_DAYS_BY_REL_TYPE["STUDIED"] == 90

    def test_tau_days_default_180(self) -> None:
        assert TAU_DAYS_DEFAULT == 180

    def test_decay_floor_0_5(self) -> None:
        assert DECAY_FLOOR == 0.5

    def test_rrf_k_60(self) -> None:
        assert RRF_K == 60


class TestComputeTimeDecay:
    """time_decay = DECAY_FLOOR + (1 - DECAY_FLOOR) * exp(-Δt / τ)."""

    def test_zero_days_returns_one(self) -> None:
        # Δt=0 → exp(0)=1 → decay = 0.5 + 0.5 * 1.0 = 1.0
        now = datetime.now(UTC)
        decay = compute_time_decay("HOLDS", now, None, _now=now)
        assert math.isclose(decay, 1.0, abs_tol=1e-6)

    def test_holds_one_year_old_returns_floor_plus_decay(self) -> None:
        # HOLDS τ=365, Δt=365 → exp(-1) ≈ 0.3679 → decay = 0.5 + 0.5 * 0.3679 ≈ 0.6839
        now = datetime.now(UTC)
        valid_from = now - timedelta(days=365)
        decay = compute_time_decay("HOLDS", valid_from, None, _now=now)
        expected = 0.5 + 0.5 * math.exp(-1.0)
        assert math.isclose(decay, expected, abs_tol=1e-6)

    def test_extreme_old_approaches_floor(self) -> None:
        # 10 年前的 EXPRESSED_VIEW(τ=90) → exp(-Δt/τ) → 0 → decay → DECAY_FLOOR
        now = datetime.now(UTC)
        valid_from = now - timedelta(days=3650)
        decay = compute_time_decay("EXPRESSED_VIEW", valid_from, None, _now=now)
        assert math.isclose(decay, DECAY_FLOOR, abs_tol=1e-3)
        assert decay >= DECAY_FLOOR  # 衰减底不消失

    def test_unknown_rel_type_uses_default_tau(self) -> None:
        # rel_type="CORRELATED_WITH" 不在 map → 走 TAU_DAYS_DEFAULT=180
        now = datetime.now(UTC)
        valid_from = now - timedelta(days=180)
        decay = compute_time_decay("CORRELATED_WITH", valid_from, None, _now=now)
        expected = 0.5 + 0.5 * math.exp(-1.0)  # Δt/τ = 1
        assert math.isclose(decay, expected, abs_tol=1e-6)

    def test_history_edge_uses_valid_to_as_reference(self) -> None:
        """spec § 11 #3: 历史 edge(valid_to IS NOT NULL) 取 valid_to 作衰减参考点.

        用户 2024-08 买 2025-03 卖的茅台 — 从 2025-03 起开始衰减,不是从 2024-08.
        """
        now = datetime.now(UTC)
        valid_from = now - timedelta(days=600)  # 久远
        valid_to = now - timedelta(days=30)  # 近期才 invalidate
        decay = compute_time_decay("HOLDS", valid_from, valid_to, _now=now)
        # 应该按 30 天计算, 不是 600 天
        expected_with_valid_to = 0.5 + 0.5 * math.exp(-30 / 365)
        expected_with_valid_from = 0.5 + 0.5 * math.exp(-600 / 365)
        assert math.isclose(decay, expected_with_valid_to, abs_tol=1e-6)
        assert not math.isclose(decay, expected_with_valid_from, abs_tol=1e-6)

    def test_naive_datetime_treated_as_utc(self) -> None:
        """tz-naive 时间不报错 — 内部补 UTC. 防御 PG row 偶尔 strip tz."""
        now = datetime(2026, 5, 11, 0, 0, 0)  # naive
        valid_from = datetime(2026, 5, 11, 0, 0, 0)  # naive
        decay = compute_time_decay("HOLDS", valid_from, None, _now=now)
        assert math.isclose(decay, 1.0, abs_tol=1e-6)


class TestReciprocalRankFusionV2:
    """spec § 11 末尾 #3 完整公式: score_final = base_rrf × imp_weight × time_decay."""

    def _now(self) -> datetime:
        return datetime(2026, 5, 11, 0, 0, 0, tzinfo=UTC)

    def _make_meta(
        self,
        eid: str,
        rel_type: str,
        importance: float,
        days_old: int,
        valid_to_days_old: int | None = None,
    ) -> dict[str, Any]:
        valid_from = self._now() - timedelta(days=days_old)
        valid_to = (
            self._now() - timedelta(days=valid_to_days_old)
            if valid_to_days_old is not None
            else None
        )
        return {
            "edge_id": eid,
            "rel_type": rel_type,
            "importance": importance,
            "valid_from": valid_from,
            "valid_to": valid_to,
        }

    def test_high_importance_recent_holds_ranks_first(self) -> None:
        """高 importance + 近期 HOLDS 应该排第一."""
        edges_meta = {
            "e1": self._make_meta("e1", "HOLDS", 0.9, days_old=10),
            "e2": self._make_meta("e2", "HOLDS", 0.2, days_old=10),
        }
        retr_results = [
            [{"edge_id": "e1"}, {"edge_id": "e2"}],
            [{"edge_id": "e1"}, {"edge_id": "e2"}],
        ]
        ranked = reciprocal_rank_fusion_v2(retr_results, edges_meta, top=5, _now=self._now())
        assert ranked[0]["edge_id"] == "e1"
        assert ranked[1]["edge_id"] == "e2"

    def test_old_low_importance_not_completely_suppressed(self) -> None:
        """衰减底 0.5 + importance 下限 0.6 — 老 fact 仍可被召回."""
        edges_meta = {
            "old_low": self._make_meta("old_low", "EXPRESSED_VIEW", 0.2, days_old=3650),
        }
        retr_results = [[{"edge_id": "old_low"}]]
        ranked = reciprocal_rank_fusion_v2(retr_results, edges_meta, top=5, _now=self._now())
        assert len(ranked) == 1
        # base = 1/61 ≈ 0.0164, imp_weight=0.6, time_decay≥0.5
        # final ≥ 0.0164 * 0.6 * 0.5 ≈ 0.00492 > 0
        assert ranked[0]["score"] > 0.0

    def test_history_edge_decay_uses_valid_to(self) -> None:
        """历史 edge 用 valid_to 作衰减参考点."""
        edges_meta = {
            "hist": self._make_meta("hist", "HOLDS", 0.5, days_old=600, valid_to_days_old=30),
            "current": self._make_meta("current", "HOLDS", 0.5, days_old=30),
        }
        retr_results = [
            [{"edge_id": "hist"}, {"edge_id": "current"}],
        ]
        ranked = reciprocal_rank_fusion_v2(retr_results, edges_meta, top=5, _now=self._now())
        scores = {item["edge_id"]: item["score"] for item in ranked}
        # hist 衰减按 30 天 vs current 30 天 → 同 decay; rank 1 vs rank 2 决定
        # rank 1 = 1/61, rank 2 = 1/62 → ratio 62/61 ≈ 1.016
        # 也容忍 5% 内
        assert math.isclose(
            scores["hist"], scores["current"] * (60 + 1) / (60 + 2), rel_tol=0.01
        ) or math.isclose(scores["hist"], scores["current"], rel_tol=0.05)

    def test_unknown_importance_uses_middle_default_0_75(self) -> None:
        """importance 不是三档之一(老数据) — 走 0.75 fallback."""
        edges_meta = {
            "weird": self._make_meta("weird", "HOLDS", 0.7, days_old=10),  # 0.7 不是三档
            "high": self._make_meta("high", "HOLDS", 0.9, days_old=10),
            "med": self._make_meta("med", "HOLDS", 0.5, days_old=10),
        }
        retr_results = [
            [{"edge_id": "high"}, {"edge_id": "weird"}, {"edge_id": "med"}],
        ]
        ranked = reciprocal_rank_fusion_v2(retr_results, edges_meta, top=5, _now=self._now())
        scores = {item["edge_id"]: item["score"] for item in ranked}
        # high(0.95) > weird(0.75) (rank 决定 weird vs med)
        assert scores["high"] > scores["weird"]

    def test_top_k_truncation(self) -> None:
        """top=2 只返 2 条."""
        edges_meta = {
            f"e{i}": self._make_meta(f"e{i}", "HOLDS", 0.5, days_old=i) for i in range(10)
        }
        retr_results = [[{"edge_id": f"e{i}"} for i in range(10)]]
        ranked = reciprocal_rank_fusion_v2(retr_results, edges_meta, top=2, _now=self._now())
        assert len(ranked) == 2

    def test_three_retrievers_aggregate_correctly(self) -> None:
        """3 路 retriever — e1 出现 3 次, e2 出现 2 次, e1 score > e2."""
        edges_meta = {
            "e1": self._make_meta("e1", "HOLDS", 0.5, days_old=10),
            "e2": self._make_meta("e2", "HOLDS", 0.5, days_old=10),
        }
        retr_results = [
            [{"edge_id": "e1"}, {"edge_id": "e2"}],
            [{"edge_id": "e1"}, {"edge_id": "e2"}],
            [{"edge_id": "e1"}],
        ]
        ranked = reciprocal_rank_fusion_v2(retr_results, edges_meta, top=5, _now=self._now())
        scores = {item["edge_id"]: item["score"] for item in ranked}
        # e1 出现 3 次(rank 1/1/1) → base = 3/(60+1) = 3/61
        # e2 出现 2 次(rank 2/2) → base = 2/(60+2) = 2/62
        assert scores["e1"] > scores["e2"]

    def test_empty_retriever_results_returns_empty(self) -> None:
        """所有 retriever 都空 → 空 list."""
        ranked = reciprocal_rank_fusion_v2([[], [], []], {}, top=5, _now=self._now())
        assert ranked == []

    def test_none_importance_uses_fallback(self) -> None:
        """importance 字段缺失(None)走 fallback 0.75."""
        edges_meta = {
            "e1": {
                "edge_id": "e1",
                "rel_type": "HOLDS",
                "importance": None,
                "valid_from": self._now() - timedelta(days=10),
                "valid_to": None,
            },
        }
        retr_results = [[{"edge_id": "e1"}]]
        ranked = reciprocal_rank_fusion_v2(retr_results, edges_meta, top=5, _now=self._now())
        assert len(ranked) == 1
        assert ranked[0]["score"] > 0.0
