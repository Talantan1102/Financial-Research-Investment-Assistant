"""KBBacktestAdapter unit tests — Phase 1 Task 1.5.

spec § 4.5 决策 5 time-travel 数据控制(KB chunk 层)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from unittest.mock import MagicMock

import pytest


@dataclass
class _FakeChunk:
    chunk_id: str
    text: str
    publish_date: date | None


def test_kb_adapter_drops_chunks_after_cut_off() -> None:
    """KB 搜索结果中 publish_date > cut_off 的 chunk 被过滤掉."""
    from eval.dd_report.kb_backtest_adapter import KBBacktestAdapter

    inner = MagicMock()
    inner.search.return_value = [
        _FakeChunk(chunk_id="c1", text="2024 Q1 财报数据", publish_date=date(2024, 3, 30)),
        _FakeChunk(chunk_id="c2", text="2024 Q3 财报数据", publish_date=date(2024, 9, 30)),
    ]

    adapter = KBBacktestAdapter(inner=inner, cut_off=date(2024, 6, 30))
    chunks = adapter.search(query="茅台财报", k=10)

    ids = {c.chunk_id for c in chunks}
    assert ids == {"c1"}
    assert "c2" not in ids


def test_kb_adapter_drops_none_publish_date_in_strict_mode() -> None:
    """strict 模式下 publish_date is None 也被丢(无法证伪 leak)."""
    from eval.dd_report.kb_backtest_adapter import KBBacktestAdapter

    inner = MagicMock()
    inner.search.return_value = [
        _FakeChunk(chunk_id="c1", text="带日期", publish_date=date(2024, 3, 30)),
        _FakeChunk(chunk_id="c2", text="无日期", publish_date=None),
    ]

    adapter = KBBacktestAdapter(inner=inner, cut_off=date(2024, 6, 30), strict_no_date=True)
    chunks = adapter.search(query="任意", k=10)
    assert {c.chunk_id for c in chunks} == {"c1"}


def test_kb_adapter_keeps_none_publish_date_in_lenient_mode() -> None:
    """lenient 模式(默认)— publish_date is None 保留(历史 chunk 兼容)."""
    from eval.dd_report.kb_backtest_adapter import KBBacktestAdapter

    inner = MagicMock()
    inner.search.return_value = [
        _FakeChunk(chunk_id="c1", text="带日期", publish_date=date(2024, 3, 30)),
        _FakeChunk(chunk_id="c2", text="无日期", publish_date=None),
    ]

    adapter = KBBacktestAdapter(inner=inner, cut_off=date(2024, 6, 30))
    chunks = adapter.search(query="任意", k=10)
    assert {c.chunk_id for c in chunks} == {"c1", "c2"}


def test_kb_adapter_cut_off_required() -> None:
    """cut_off 必填."""
    from eval.dd_report.kb_backtest_adapter import KBBacktestAdapter

    with pytest.raises(TypeError):
        KBBacktestAdapter(inner=MagicMock())  # type: ignore[call-arg]
