"""Memory tool routing accuracy metric — Plan 4 skeleton, Plan 8 fills 50 cases.

Inputs (Plan 8 will load from `c5_memory_golden.jsonl` etc.):
    cases: list of {
        "query": str,            # user utterance
        "expected_tool": str,    # ground-truth memory MCP tool name
        "predicted_tool": str,   # supervisor's chosen tool
    }

Output:
    {
        "total": int,
        "correct": int,
        "accuracy": float,                       # correct / total (0 if total==0)
        "per_tool_recall": {tool_name: float},  # one entry per MEMORY_TOOLS
        "errors": [{query, expected, predicted}],
    }

Plan 8 will add:
    - thresholds (e.g. assert accuracy > 0.7)
    - per-tool precision / F1 (currently only recall)
    - confusion matrix output
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

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
