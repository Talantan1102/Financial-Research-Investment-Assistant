"""L0 — PB valuation helper."""

from __future__ import annotations

import math

import pytest


def test_pb_normal_case() -> None:
    """bvps=250, 行业 PB 1.5-2.0 → 理论价 ≈ 250 × 1.75 = 437.5"""
    from app.agents.valuation_helpers.pb import compute_pb_value

    price = compute_pb_value(
        book_value_per_share=250.0, industry_pb_avg=2.0, industry_pb_median=1.5
    )
    assert price == pytest.approx(250.0 * 1.75, rel=0.01)


def test_pb_raises_for_negative_bvps() -> None:
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError
    from app.agents.valuation_helpers.pb import compute_pb_value

    with pytest.raises(InsufficientDataForModelError):
        compute_pb_value(book_value_per_share=-10.0, industry_pb_avg=2.0, industry_pb_median=2.0)


def test_pb_raises_for_zero_bvps() -> None:
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError
    from app.agents.valuation_helpers.pb import compute_pb_value

    with pytest.raises(InsufficientDataForModelError):
        compute_pb_value(book_value_per_share=0.0, industry_pb_avg=2.0, industry_pb_median=2.0)


def test_pb_raises_for_invalid_industry_pb() -> None:
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError
    from app.agents.valuation_helpers.pb import compute_pb_value

    with pytest.raises(InsufficientDataForModelError):
        compute_pb_value(book_value_per_share=250.0, industry_pb_avg=0.0, industry_pb_median=0.0)
    # 任一为负也 raise(严格 guard,跟 PE 同范式)
    with pytest.raises(InsufficientDataForModelError):
        compute_pb_value(book_value_per_share=250.0, industry_pb_avg=-1.0, industry_pb_median=2.0)


def test_pb_heavy_asset_case() -> None:
    """重资产银行:bvps=10, 行业 PB 0.8-1.0 → 理论价 ≈ 9"""
    from app.agents.valuation_helpers.pb import compute_pb_value

    price = compute_pb_value(book_value_per_share=10.0, industry_pb_avg=1.0, industry_pb_median=0.8)
    assert price == pytest.approx(10.0 * 0.9, rel=0.01)


def test_pb_raises_on_nan_input() -> None:
    """NaN 任一输入 → raise (防污染 cross-check consistency)."""
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError
    from app.agents.valuation_helpers.pb import compute_pb_value

    with pytest.raises(InsufficientDataForModelError):
        compute_pb_value(book_value_per_share=math.nan, industry_pb_avg=2.0, industry_pb_median=1.5)
    with pytest.raises(InsufficientDataForModelError):
        compute_pb_value(
            book_value_per_share=250.0, industry_pb_avg=math.nan, industry_pb_median=1.5
        )


def test_pb_raises_on_inf_input() -> None:
    """inf 同理."""
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError
    from app.agents.valuation_helpers.pb import compute_pb_value

    with pytest.raises(InsufficientDataForModelError):
        compute_pb_value(book_value_per_share=math.inf, industry_pb_avg=2.0, industry_pb_median=1.5)
