"""L0 unit: routing_accuracy (subset-match) — Plan 8 multi-tool variant.

区别于 test_routing_metric_skeleton.py(Plan 4 单 tool exact match).
Plan 8 subset match: expected_tools ⊆ actual_tools 算 correct.
"""

from __future__ import annotations

import pytest

from backend.eval.memory.routing_accuracy_metric import routing_accuracy


class _Plan:
    def __init__(self, tool_names: list[str]) -> None:
        self.tool_calls = [type("TC", (), {"tool_name": n})() for n in tool_names]


class _MockPlanner:
    def __init__(self, mapping: dict[str, list[str]]) -> None:
        self._mapping = mapping

    async def plan(self, query: str) -> _Plan:
        return _Plan(self._mapping.get(query, []))


@pytest.mark.asyncio
async def test_routing_accuracy_all_correct() -> None:
    cases = [
        {"query": "我对茅台看法", "expected_tools": ["archival_memory_search"]},
        {"query": "跟我持仓相关", "expected_tools": ["archival_memory_traverse"]},
    ]
    planner = _MockPlanner(
        {
            "我对茅台看法": ["archival_memory_search"],
            "跟我持仓相关": ["archival_memory_traverse"],
        }
    )
    acc = await routing_accuracy(planner=planner, golden_cases=cases)
    assert acc == 1.0


@pytest.mark.asyncio
async def test_routing_accuracy_subset_match_extra_tool_ok() -> None:
    """expected ⊆ actual (extra tools 允许, 不算 wrong)."""
    cases = [{"query": "q", "expected_tools": ["search"]}]
    planner = _MockPlanner({"q": ["search", "extra_tool"]})
    acc = await routing_accuracy(planner=planner, golden_cases=cases)
    assert acc == 1.0


@pytest.mark.asyncio
async def test_routing_accuracy_missing_expected_tool_is_wrong() -> None:
    cases = [{"query": "q", "expected_tools": ["search"]}]
    planner = _MockPlanner({"q": ["traverse"]})
    acc = await routing_accuracy(planner=planner, golden_cases=cases)
    assert acc == 0.0


@pytest.mark.asyncio
async def test_routing_accuracy_partial() -> None:
    cases = [
        {"query": "q1", "expected_tools": ["search"]},
        {"query": "q2", "expected_tools": ["traverse"]},
    ]
    planner = _MockPlanner({"q1": ["search"], "q2": ["search"]})
    acc = await routing_accuracy(planner=planner, golden_cases=cases)
    assert acc == 0.5


@pytest.mark.asyncio
async def test_routing_accuracy_both_routing() -> None:
    """memory + kb 同时触发 — expected_tools = ['memory_search', 'kb_search']."""
    cases = [
        {
            "query": "结合我持仓推荐研报",
            "expected_tools": ["archival_memory_search", "kb_search"],
        }
    ]
    planner = _MockPlanner({"结合我持仓推荐研报": ["archival_memory_search", "kb_search"]})
    acc = await routing_accuracy(planner=planner, golden_cases=cases)
    assert acc == 1.0


@pytest.mark.asyncio
async def test_routing_accuracy_empty_cases() -> None:
    planner = _MockPlanner({})
    acc = await routing_accuracy(planner=planner, golden_cases=[])
    assert acc == 0.0


@pytest.mark.asyncio
async def test_routing_accuracy_meets_threshold_85pct() -> None:
    """spec § 10 routing accuracy ≥ 0.85 — 17/20 = 0.85 should pass."""
    cases = [{"query": f"q{i}", "expected_tools": ["search"]} for i in range(20)]
    # 17 correct (planner returns search) + 3 wrong (returns traverse)
    mapping = {f"q{i}": (["search"] if i < 17 else ["traverse"]) for i in range(20)}
    planner = _MockPlanner(mapping)
    acc = await routing_accuracy(planner=planner, golden_cases=cases)
    assert acc == pytest.approx(0.85)
    assert acc >= 0.85
