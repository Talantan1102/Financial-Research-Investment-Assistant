"""L1 integration: eval_runner.run_all over 50 golden case with mock deps.

不需要真 LLM / DB; 测试 eval_runner 编排正确性 + 各 metric 调用路径 + threshold gate.
"""

from __future__ import annotations

from datetime import UTC
from pathlib import Path
from typing import Any

import pytest

from backend.eval.memory.eval_runner import (
    METRIC_THRESHOLDS,
    assert_thresholds,
    load_golden_cases,
    run_all,
)

GOLDEN_PATH = Path(__file__).resolve().parents[3] / "eval" / "memory" / "c5_memory_golden.jsonl"


# ---------------------------------------------------------------------------
# Mock deps — judge / planner / retriever 都 hard-coded high score
# ---------------------------------------------------------------------------


class _OkJudge:
    """Always returns yes / claim list / grounded=True → metric mean = 1.0."""

    async def eval(self, query: str, fact: dict[str, Any], prompt: str) -> str:
        return "yes"

    async def decompose_to_claims(self, answer: str) -> list[str]:
        return [answer[:20]] if answer else []

    async def is_grounded(self, claim: str, facts: list[dict[str, Any]]) -> bool:
        return True


class _Plan:
    def __init__(self, tools: list[str]) -> None:
        self.tool_calls = [type("TC", (), {"tool_name": n})() for n in tools]


class _OkPlanner:
    """从 golden case 拿 expected_tools 全 return → routing_accuracy = 1.0."""

    def __init__(self, cases: list[dict[str, Any]]) -> None:
        self._mapping = {c["query"]: c["expected_tools"] for c in cases}

    async def plan(self, query: str) -> _Plan:
        return _Plan(self._mapping.get(query, ["archival_memory_search"]))


class _OkRetriever:
    """Returns 5 fake facts (valid_from spread 30-200 day) so long_tail passes.

    For queries with expected_time_range, returns facts inside that window so
    temporal_correctness can pass.
    """

    def __init__(self, cases: list[dict[str, Any]] | None = None) -> None:
        from datetime import datetime, timedelta

        now = datetime.now(UTC)
        self._default_facts = [
            {
                "edge_id": f"e{i}",
                "rel_type": "HOLDS",
                "source_label": "User",
                "target_label": "Stock:600519.SH",
                "valid_from": now - timedelta(days=30 * (i + 1)),
                "valid_to": None,
            }
            for i in range(5)
        ]
        # Pre-build per-query facts inside expected_time_range
        self._per_query: dict[str, list[dict[str, Any]]] = {}
        for c in cases or []:
            rng = c.get("expected_time_range")
            if rng is None:
                continue
            start = datetime.fromisoformat(rng[0]).replace(tzinfo=UTC)
            end = datetime.fromisoformat(rng[1]).replace(tzinfo=UTC)
            mid = start + (end - start) / 2
            self._per_query[c["query"]] = [
                {
                    "edge_id": f"in-range-{c['case_id']}-{i}",
                    "rel_type": "HOLDS",
                    "source_label": "User",
                    "target_label": "Stock:600519.SH",
                    "valid_from": mid,
                    "valid_to": None,
                }
                for i in range(5)
            ]

    async def archival_memory_search(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        if query in self._per_query:
            return list(self._per_query[query][:k])
        return list(self._default_facts[:k])

    async def generate_answer(self, query: str, facts: list[dict[str, Any]]) -> str:
        return f"用户在 {query} 相关方面有持仓"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_load_golden_cases_returns_50() -> None:
    cases = load_golden_cases(GOLDEN_PATH)
    assert len(cases) == 50


@pytest.mark.asyncio
async def test_run_all_with_ok_mocks_meets_all_thresholds() -> None:
    cases = load_golden_cases(GOLDEN_PATH)
    judge = _OkJudge()
    planner = _OkPlanner(cases)
    retriever = _OkRetriever(cases)

    results = await run_all(GOLDEN_PATH, judge, planner, retriever)
    failures = assert_thresholds(results)

    # 所有 metric 应该 pass
    assert failures == [], f"expected no failures, got: {failures}"

    # case_counts 正确
    assert results["case_counts"]["retrieval"] == 20
    assert results["case_counts"]["routing"] == 20
    assert results["case_counts"]["extraction"] == 10

    # 各 metric mean
    bm = results["by_metric"]
    assert bm["recall_precision"]["mean"] == 1.0
    assert bm["recall_precision"]["count"] == 20
    assert bm["routing_accuracy"]["value"] == 1.0
    assert bm["routing_accuracy"]["count"] == 20
    assert bm["faithful_answer"]["mean"] == 1.0
    assert bm["long_tail"]["violated"] is False


@pytest.mark.asyncio
async def test_assert_thresholds_catches_low_recall() -> None:
    results = {
        "by_metric": {
            "recall_precision": {"mean": 0.5},
            "temporal_correctness": {"mean": 1.0},
            "faithful_answer": {"mean": 1.0},
            "routing_accuracy": {"value": 1.0},
            "long_tail": {"violated": False, "p90_min_age_days": 100},
        }
    }
    failures = assert_thresholds(results)
    assert any("recall_precision" in f for f in failures)


@pytest.mark.asyncio
async def test_assert_thresholds_catches_low_routing() -> None:
    results = {
        "by_metric": {
            "recall_precision": {"mean": 1.0},
            "temporal_correctness": {"mean": 1.0},
            "faithful_answer": {"mean": 1.0},
            "routing_accuracy": {"value": 0.5},
            "long_tail": {"violated": False, "p90_min_age_days": 100},
        }
    }
    failures = assert_thresholds(results)
    assert any("routing_accuracy" in f for f in failures)


@pytest.mark.asyncio
async def test_assert_thresholds_catches_long_tail_violation() -> None:
    results = {
        "by_metric": {
            "recall_precision": {"mean": 1.0},
            "temporal_correctness": {"mean": 1.0},
            "faithful_answer": {"mean": 1.0},
            "routing_accuracy": {"value": 1.0},
            "long_tail": {
                "violated": True,
                "p90_min_age_days": 3,
                "p90_floor_days": 7,
            },
        }
    }
    failures = assert_thresholds(results)
    assert any("long_tail" in f for f in failures)


def test_metric_thresholds_match_spec() -> None:
    """spec § 10 阈值 freeze (PR gate 用)."""
    assert METRIC_THRESHOLDS["recall_precision"] == 0.7
    assert METRIC_THRESHOLDS["temporal_correctness"] == 0.95
    assert METRIC_THRESHOLDS["faithful_answer"] == 0.85
    assert METRIC_THRESHOLDS["routing_accuracy"] == 0.85
    assert METRIC_THRESHOLDS["long_tail_p90_min_days"] == 7
