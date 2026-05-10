"""L0 — RecallSearcher pure-function bits + cosine.

Real DB tests live in backend/tests/integration/memory/test_recall_search.py.
"""

from __future__ import annotations

import math


def test_cosine_basic() -> None:
    from app.memory.recall_search import _cosine

    assert _cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    # opposite
    assert _cosine([1.0, 0.0], [-1.0, 0.0]) == -1.0


def test_cosine_zero_vector_returns_zero() -> None:
    from app.memory.recall_search import _cosine

    assert _cosine([0.0, 0.0], [1.0, 0.0]) == 0.0
    assert _cosine([1.0, 0.0], [0.0, 0.0]) == 0.0


def test_cosine_normalized() -> None:
    from app.memory.recall_search import _cosine

    val = _cosine([3.0, 4.0], [3.0, 4.0])  # ||v||=5, dot=25, cos=1.0
    assert math.isclose(val, 1.0)
