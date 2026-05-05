"""Unit tests for lookup_industry_benchmark (deterministic JSON lookup)."""

from __future__ import annotations

import pytest
from app.skills.financial_research.scripts.lookup_industry_benchmark import (
    lookup_industry_benchmark,
)


def test_known_industry_returns_industry_value() -> None:
    val = lookup_industry_benchmark(industry="白酒", indicator="ROE_行业平均")
    # 白酒 ROE_行业平均 is intentionally distinct from DEFAULT (0.10)
    assert val == pytest.approx(0.18)


def test_unknown_industry_falls_back_to_default() -> None:
    val = lookup_industry_benchmark(industry="不存在的行业", indicator="ROE_行业平均")
    assert val == pytest.approx(0.10)
