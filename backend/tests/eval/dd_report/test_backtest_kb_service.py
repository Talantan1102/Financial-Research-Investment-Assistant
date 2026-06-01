"""Unit tests for _BacktestKbService in dd_report_production_factory.

C42: ensures unknown KB adapter result types raise TypeError (fail-loud) instead
of being silently dropped, which would corrupt ablation metric counts.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


def _make_service(results: list[Any]) -> Any:
    """Build a _BacktestKbService backed by a stub adapter returning *results*."""
    from app.eval.dd_report_production_factory import _BacktestKbService

    inner = MagicMock()
    inner.search.return_value = results
    return _BacktestKbService(inner)


def _make_kb_hit(chunk_id: str = "c1", chunk_text: str = "text") -> Any:
    """Build a real KbHit instance."""
    from app.services.kb_search_service import KbHit

    return KbHit(chunk_id=chunk_id, chunk_text=chunk_text, similarity=0.9, metadata={})


# ---------------------------------------------------------------------------
# Happy-path: KbHit items pass through unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_returns_kbhit_items_unchanged() -> None:
    """KbHit items in the adapter result are returned as-is."""
    hit = _make_kb_hit("id1", "hello world")
    service = _make_service([hit])
    results = await service.search(query="q")
    assert len(results) == 1
    assert results[0].chunk_id == "id1"
    assert results[0].chunk_text == "hello world"


# ---------------------------------------------------------------------------
# Happy-path: dict items are converted to KbHit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_converts_dict_items_to_kbhit() -> None:
    """dict items are converted to KbHit with the expected fields."""
    from app.services.kb_search_service import KbHit

    service = _make_service(
        [
            {
                "chunk_id": "d1",
                "chunk_text": "body text",
                "similarity": 0.75,
                "extra_field": "ignored",
            }
        ]
    )
    results = await service.search(query="q")
    assert len(results) == 1
    assert isinstance(results[0], KbHit)
    assert results[0].chunk_id == "d1"
    assert results[0].chunk_text == "body text"
    assert results[0].similarity == pytest.approx(0.75)
    assert "extra_field" in results[0].metadata


# ---------------------------------------------------------------------------
# C42 regression: unknown types must raise TypeError (not silently drop)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_raises_type_error_for_unknown_result_type_int() -> None:
    """An int in the adapter result raises TypeError (C42 regression)."""
    service = _make_service([42])
    with pytest.raises(TypeError, match="unexpected KB adapter result type.*'int'"):
        await service.search(query="q")


@pytest.mark.asyncio
async def test_search_raises_type_error_for_unknown_result_type_string() -> None:
    """A bare string in the adapter result raises TypeError (C42 regression)."""
    service = _make_service(["unexpected string"])
    with pytest.raises(TypeError, match="unexpected KB adapter result type.*'str'"):
        await service.search(query="q")


@pytest.mark.asyncio
async def test_search_raises_type_error_for_unknown_result_type_list() -> None:
    """A nested list in the adapter result raises TypeError (C42 regression)."""
    service = _make_service([["nested", "list"]])
    with pytest.raises(TypeError, match="unexpected KB adapter result type.*'list'"):
        await service.search(query="q")


@pytest.mark.asyncio
async def test_search_raises_on_first_bad_item_in_mixed_list() -> None:
    """TypeError fires on the first unexpected item even if earlier items are valid."""
    hit = _make_kb_hit("ok", "valid")
    service = _make_service([hit, 99])
    with pytest.raises(TypeError, match="unexpected KB adapter result type.*'int'"):
        await service.search(query="q")
