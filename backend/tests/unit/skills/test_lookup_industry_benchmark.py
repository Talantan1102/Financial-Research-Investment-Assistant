"""Unit tests for lookup_industry_benchmark (deterministic JSON lookup)."""

from __future__ import annotations

from app.skills.financial_research.scripts.lookup_industry_benchmark import (
    lookup_industry_benchmark,
)


def test_lookup_known_industry() -> None:
    assert lookup_industry_benchmark(industry="白酒", indicator="ROE_行业平均") == 0.20


def test_lookup_unknown_industry_falls_back_to_default() -> None:
    assert lookup_industry_benchmark(industry="未知行业", indicator="资产负债率_健康") == 0.50
