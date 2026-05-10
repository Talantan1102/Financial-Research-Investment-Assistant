"""Memory vs KB routing accuracy metric hook — Plan 6 提供, Plan 8 填实 50 case + 阈值 ≥ 0.85.

Distinguished from `routing_accuracy_metric.py` (Plan 4) which targets memory-MCP-tool
selection. This hook is for the supervisor-level **memory vs kb retrieval** routing
(spec § 11 末尾 #7).

usage(Plan 8 will扩到 50 case):

    from backend.eval.memory.routing_accuracy_hook import (
        RoutingCase, compute_routing_accuracy, load_routing_cases,
    )
    cases = load_routing_cases("backend/eval/memory/c5_memory_golden.jsonl")
    predictions = {c.query: predict(c.query) for c in cases}
    acc = compute_routing_accuracy(cases, predictions)
    assert acc >= 0.85
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

RoutingTarget = Literal["memory", "kb", "both"]


class RoutingCase(BaseModel):
    """One labeled routing test case.

    Plan 6 ship: 8 seed cases (2 memory + 2 kb + 2 both + 2 boundary).
    Plan 8 will extend to 50 cases keeping balanced distribution.
    """

    model_config = ConfigDict(frozen=True)

    query: str
    expected: RoutingTarget
    category: str = "uncategorized"

    @field_validator("expected")
    @classmethod
    def _check_expected(cls, v: str) -> str:
        if v not in ("memory", "kb", "both"):
            raise ValueError(f"Invalid expected target: {v!r}")
        return v


def load_routing_cases(path: str | Path) -> list[RoutingCase]:
    """Load routing cases from a JSONL file (one JSON object per non-blank line)."""
    p = Path(path)
    cases: list[RoutingCase] = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            cases.append(RoutingCase.model_validate(json.loads(stripped)))
    return cases


def compute_routing_accuracy(
    cases: list[RoutingCase],
    predictions: dict[str, str],
) -> float:
    """Compute exact-match accuracy of routing predictions.

    Args:
        cases: ground-truth labeled cases (positional ordering preserved)
        predictions: ``{query: predicted_target}`` — missing prediction
            counts as wrong (defensive, not silently passing).

    Returns:
        accuracy ∈ [0.0, 1.0]; 0.0 when ``cases`` is empty.
    """
    if not cases:
        return 0.0
    correct = 0
    for c in cases:
        if predictions.get(c.query) == c.expected:
            correct += 1
    return correct / len(cases)
