"""Memory tool routing accuracy metric.

Plan 4 ship: compute_routing_accuracy (single-tool exact-match).
Plan 8 ship: routing_accuracy (multi-tool subset-match — works on
c5_memory_golden.jsonl 20 routing case 的 expected_tools: list[str]).

Inputs:
    cases: list of {
        "query": str,
        "expected_tools": list[str],   # Plan 8 schema (subset match)
        ...
    }
    planner: object with `.plan(query) -> Plan` 返回含 `.tool_calls[].tool_name`.

spec § 10 routing accuracy ≥ 0.85.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Protocol

MEMORY_TOOLS: list[str] = [
    "core_memory_append",
    "core_memory_replace",
    "archival_memory_insert",
    "archival_memory_search",
    "archival_memory_traverse",
    "recall_memory_search",
]


def compute_routing_accuracy(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Returns total/correct/accuracy + per-tool recall + error list.

    Args:
        cases: list of dicts with keys "query", "expected_tool",
            "predicted_tool".

    Empty cases list returns zeros (no division by zero).
    """
    total = len(cases)
    correct = 0
    per_tool_total: dict[str, int] = defaultdict(int)
    per_tool_correct: dict[str, int] = defaultdict(int)
    errors: list[dict[str, Any]] = []

    for c in cases:
        exp = c["expected_tool"]
        pred = c["predicted_tool"]
        per_tool_total[exp] += 1
        if exp == pred:
            correct += 1
            per_tool_correct[exp] += 1
        else:
            errors.append(
                {
                    "query": c.get("query", ""),
                    "expected": exp,
                    "predicted": pred,
                }
            )

    per_tool_recall = {
        tool: (per_tool_correct[tool] / per_tool_total[tool]) if per_tool_total[tool] > 0 else 0.0
        for tool in MEMORY_TOOLS
    }

    return {
        "total": total,
        "correct": correct,
        "accuracy": (correct / total) if total > 0 else 0.0,
        "per_tool_recall": per_tool_recall,
        "errors": errors,
    }


# ============================================================================
# Plan 8 — subset-match routing_accuracy (works on golden case
# `expected_tools: list[str]` schema, used by eval_runner Task 11)
# ============================================================================


class PlannerProtocol(Protocol):
    """planner 抽象 — 真 chat agent / supervisor 调 .plan(query) 输出 tool 调用计划."""

    async def plan(self, query: str) -> Any: ...


async def routing_accuracy(
    planner: PlannerProtocol,
    golden_cases: list[dict[str, Any]],
) -> float:
    """spec § 10 subset-match routing accuracy.

    for each case:
        plan = await planner.plan(case["query"])
        actual_tools = {tc.tool_name for tc in plan.tool_calls}
        correct += set(case["expected_tools"]).issubset(actual_tools)
    return correct / len(cases)

    Empty cases → 0.0.
    """
    if not golden_cases:
        return 0.0
    correct = 0
    for case in golden_cases:
        plan_obj = await planner.plan(case["query"])
        actual = {tc.tool_name for tc in plan_obj.tool_calls}
        expected = set(case["expected_tools"])
        if expected.issubset(actual):
            correct += 1
    return correct / len(golden_cases)
