"""Unit tests for lookup_industry_benchmark (deterministic JSON lookup)."""

from __future__ import annotations

import importlib

import pytest
from app.skills.financial_research.scripts.lookup_industry_benchmark import (
    lookup_industry_benchmark,
)

lookup_module = importlib.import_module(
    "app.skills.financial_research.scripts.lookup_industry_benchmark"
)


def test_lookup_known_industry() -> None:
    assert lookup_industry_benchmark(industry="白酒", indicator="ROE_行业平均") == 0.20


def test_lookup_unknown_industry_falls_back_to_default() -> None:
    assert lookup_industry_benchmark(industry="未知行业", indicator="资产负债率_健康") == 0.50


def test_lookup_indicator_missing_from_industry_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sparse industry schema → indicator-fallback path."""
    sparse_benchmarks = {
        "稀疏行业": {"ROE_行业平均": 0.99},  # missing 资产负债率_健康 etc
        "DEFAULT": lookup_module._BENCHMARKS["DEFAULT"],
    }
    monkeypatch.setattr(lookup_module, "_BENCHMARKS", sparse_benchmarks)
    # 应 fall back to DEFAULT["资产负债率_健康"] = 0.50
    assert (
        lookup_module.lookup_industry_benchmark(industry="稀疏行业", indicator="资产负债率_健康")
        == 0.50
    )


def test_lookup_private_metadata_key_raises() -> None:
    """_note 等私有 metadata key 不可作为 numeric lookup, 应 raise KeyError."""
    with pytest.raises(KeyError, match="_note"):
        lookup_industry_benchmark(industry="银行金融", indicator="_note")
