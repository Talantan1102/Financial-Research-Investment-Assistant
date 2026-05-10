"""L0 — routing accuracy metric hook 测试(Plan 6 提供 hook,Plan 8 填实 50 case)。

跟 Plan 4 的 routing_accuracy_metric.py(memory-MCP-tool 选择)区别开:
此 hook 是 supervisor 层 memory vs kb 路由 accuracy(spec § 11 末尾 #7)。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from eval.memory.routing_accuracy_hook import (
    RoutingCase,
    compute_routing_accuracy,
    load_routing_cases,
)

# backend/tests/unit/memory/test_routing_accuracy_hook.py → parents[3] = backend/
_BACKEND_DIR = Path(__file__).resolve().parents[3]
_SEED_PATH = _BACKEND_DIR / "eval" / "memory" / "routing_accuracy_seed.jsonl"


class TestRoutingCase:
    def test_valid(self) -> None:
        c = RoutingCase(query="我之前买了什么", expected="memory")
        assert c.query and c.expected == "memory"

    def test_invalid_expected_rejected(self) -> None:
        with pytest.raises(ValueError):
            RoutingCase(query="x", expected="bogus")  # type: ignore[arg-type]


class TestComputeRoutingAccuracy:
    def test_all_correct(self) -> None:
        cases = [
            RoutingCase(query="q1", expected="memory"),
            RoutingCase(query="q2", expected="kb"),
        ]
        predictions = {"q1": "memory", "q2": "kb"}
        score = compute_routing_accuracy(cases, predictions)
        assert score == 1.0

    def test_half_correct(self) -> None:
        cases = [
            RoutingCase(query="q1", expected="memory"),
            RoutingCase(query="q2", expected="kb"),
        ]
        predictions = {"q1": "memory", "q2": "memory"}
        score = compute_routing_accuracy(cases, predictions)
        assert score == 0.5

    def test_missing_prediction_counts_as_wrong(self) -> None:
        cases = [RoutingCase(query="q1", expected="memory")]
        score = compute_routing_accuracy(cases, predictions={})
        assert score == 0.0

    def test_empty_cases_returns_zero(self) -> None:
        score = compute_routing_accuracy([], predictions={})
        assert score == 0.0


class TestLoadRoutingCases:
    def test_load_seed_jsonl(self) -> None:
        assert _SEED_PATH.exists(), f"seed file missing: {_SEED_PATH}"
        cases = load_routing_cases(_SEED_PATH)
        assert len(cases) == 8  # Plan 6 seed: 8 case
        # 平衡分布: ≥ 2 memory + ≥ 2 kb + ≥ 2 both
        targets = [c.expected for c in cases]
        assert targets.count("memory") >= 2
        assert targets.count("kb") >= 2
        assert targets.count("both") >= 2
        # 至少含 1 个 boundary-noise 类
        cats = [c.category for c in cases]
        assert any("boundary" in c for c in cats)

    def test_seed_round_trip_to_metric(self) -> None:
        cases = load_routing_cases(_SEED_PATH)
        # 先验证 100% 命中(用 ground truth 当 predictions)能得 1.0
        predictions = {c.query: c.expected for c in cases}
        assert compute_routing_accuracy(cases, predictions) == 1.0
