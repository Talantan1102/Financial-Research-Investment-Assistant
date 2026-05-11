"""L0 unit: recall_precision metric — judge-based fact relevance."""

from __future__ import annotations

from typing import Any

import pytest
from eval.memory.recall_precision_metric import recall_precision


class _MockJudge:
    """Mock judge with canned yes/no verdicts."""

    def __init__(self) -> None:
        self._verdicts: list[str] = []
        self.calls: int = 0

    def set_canned_verdicts(self, verdicts: list[str]) -> None:
        self._verdicts = list(verdicts)

    async def eval(self, query: str, fact: dict[str, Any], prompt: str) -> str:
        v = self._verdicts[self.calls]
        self.calls += 1
        return v


@pytest.mark.asyncio
async def test_recall_precision_all_relevant() -> None:
    judge = _MockJudge()
    judge.set_canned_verdicts(["yes", "yes", "yes"])
    facts = [
        {"edge_id": "e1", "rel_type": "HOLDS", "target_label": "Stock:600519.SH"},
        {"edge_id": "e2", "rel_type": "EXPRESSED_VIEW", "target_label": "Stock:600519.SH"},
        {"edge_id": "e3", "rel_type": "STUDIED", "target_label": "Stock:600519.SH"},
    ]
    p = await recall_precision(query="我对茅台的看法", retrieved_facts=facts, judge=judge)
    assert p == 1.0


@pytest.mark.asyncio
async def test_recall_precision_partial() -> None:
    judge = _MockJudge()
    judge.set_canned_verdicts(["yes", "no", "yes"])
    facts = [{"edge_id": f"e{i}"} for i in range(3)]
    p = await recall_precision(query="x", retrieved_facts=facts, judge=judge)
    assert p == pytest.approx(2 / 3, abs=0.01)


@pytest.mark.asyncio
async def test_recall_precision_empty() -> None:
    p = await recall_precision(query="x", retrieved_facts=[], judge=None)
    assert p == 0.0


@pytest.mark.asyncio
async def test_recall_precision_non_empty_requires_judge() -> None:
    with pytest.raises(ValueError, match="judge required"):
        await recall_precision(query="x", retrieved_facts=[{"edge_id": "e1"}], judge=None)


@pytest.mark.asyncio
async def test_recall_precision_judge_response_case_insensitive() -> None:
    """'YES' / 'Yes  ' / 'yes!' 都算 relevant."""
    judge = _MockJudge()
    judge.set_canned_verdicts(["YES", "Yes  ", "yes!"])
    facts = [{"edge_id": "e1"}, {"edge_id": "e2"}, {"edge_id": "e3"}]
    p = await recall_precision(query="x", retrieved_facts=facts, judge=judge)
    assert p == 1.0
