"""L0 — PE valuation helper."""

from __future__ import annotations

import pytest


def test_pe_normal_case() -> None:
    """正常 case:eps=60, 行业 PE 25-30 → 理论价 ≈ 60 × 27.5 = 1650"""
    from app.agents.valuation_helpers.pe import compute_pe_value

    price = compute_pe_value(eps=60.0, industry_pe_avg=30.0, industry_pe_median=25.0)
    assert price == pytest.approx(60.0 * 27.5, rel=0.01)


def test_pe_raises_for_negative_eps() -> None:
    """亏损公司:eps ≤ 0 → InsufficientDataForModelError"""
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError
    from app.agents.valuation_helpers.pe import compute_pe_value

    with pytest.raises(InsufficientDataForModelError) as exc:
        compute_pe_value(eps=-5.0, industry_pe_avg=20.0, industry_pe_median=20.0)
    assert exc.value.model == "pe"
    assert exc.value.missing_field == "eps" or "negative" in exc.value.reason.lower()


def test_pe_raises_for_zero_eps() -> None:
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError
    from app.agents.valuation_helpers.pe import compute_pe_value

    with pytest.raises(InsufficientDataForModelError):
        compute_pe_value(eps=0.0, industry_pe_avg=20.0, industry_pe_median=20.0)


def test_pe_raises_for_invalid_industry_pe() -> None:
    """行业 PE 缺失或 ≤ 0 → InsufficientDataForModelError"""
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError
    from app.agents.valuation_helpers.pe import compute_pe_value

    with pytest.raises(InsufficientDataForModelError):
        compute_pe_value(eps=60.0, industry_pe_avg=0.0, industry_pe_median=0.0)
    with pytest.raises(InsufficientDataForModelError):
        compute_pe_value(eps=60.0, industry_pe_avg=-10.0, industry_pe_median=20.0)


def test_pe_extreme_case_does_not_raise() -> None:
    """极端 PE > 100x 仍算,helper 不抛错;caller(ValuationCalculator/Writer)负责在 narrative 中 flag。"""
    from app.agents.valuation_helpers.pe import compute_pe_value

    price = compute_pe_value(eps=1.0, industry_pe_avg=200.0, industry_pe_median=180.0)
    assert price == pytest.approx(190.0, rel=0.01)


def test_pe_raises_on_nan_input() -> None:
    """NaN 任一输入 → raise(否则会污染 cross-check consistency 算法)."""
    import math

    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError
    from app.agents.valuation_helpers.pe import compute_pe_value

    with pytest.raises(InsufficientDataForModelError):
        compute_pe_value(eps=math.nan, industry_pe_avg=30.0, industry_pe_median=25.0)
    with pytest.raises(InsufficientDataForModelError):
        compute_pe_value(eps=60.0, industry_pe_avg=math.nan, industry_pe_median=25.0)


def test_pe_raises_on_inf_input() -> None:
    """inf 同理."""
    import math

    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError
    from app.agents.valuation_helpers.pe import compute_pe_value

    with pytest.raises(InsufficientDataForModelError):
        compute_pe_value(eps=math.inf, industry_pe_avg=30.0, industry_pe_median=25.0)
