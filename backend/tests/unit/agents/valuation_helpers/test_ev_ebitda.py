"""L0 — EV/EBITDA valuation helper."""

from __future__ import annotations

import math

import pytest


def test_ev_ebitda_normal_case_low_debt() -> None:
    """茅台风格 (净现金): EBITDA=800亿, net_debt=-100亿, 行业 18-22x, shares 12.5亿
    target_ev = 800e8 × 20 = 16000e8
    implied_market_cap = 16000e8 - (-100e8) = 16100e8
    implied_price = 16100e8 / 12.5e8 = 1288
    """
    from app.agents.valuation_helpers.ev_ebitda import compute_ev_ebitda_value

    price = compute_ev_ebitda_value(
        ebitda=800e8,
        net_debt=-100e8,
        shares_outstanding=12.5e8,
        industry_ev_ebitda_avg=22.0,
        industry_ev_ebitda_median=18.0,
    )
    assert price == pytest.approx((800e8 * 20.0 - (-100e8)) / 12.5e8, rel=0.01)


def test_ev_ebitda_high_debt_case() -> None:
    """通信运营商 (高负债): EBITDA=2000亿, net_debt=5000亿, 行业 4-6x, shares 100亿
    target_ev = 2000e8 × 5 = 10000e8
    implied_market_cap = 10000e8 - 5000e8 = 5000e8
    implied_price = 5000e8 / 100e8 = 50
    """
    from app.agents.valuation_helpers.ev_ebitda import compute_ev_ebitda_value

    price = compute_ev_ebitda_value(
        ebitda=2000e8,
        net_debt=5000e8,
        shares_outstanding=100e8,
        industry_ev_ebitda_avg=6.0,
        industry_ev_ebitda_median=4.0,
    )
    assert price == pytest.approx((2000e8 * 5.0 - 5000e8) / 100e8, rel=0.01)


def test_ev_ebitda_raises_for_negative_ebitda() -> None:
    from app.agents.valuation_helpers.ev_ebitda import compute_ev_ebitda_value
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError

    with pytest.raises(InsufficientDataForModelError):
        compute_ev_ebitda_value(
            ebitda=-100e8,
            net_debt=0,
            shares_outstanding=10e8,
            industry_ev_ebitda_avg=10.0,
            industry_ev_ebitda_median=10.0,
        )


def test_ev_ebitda_raises_for_zero_ebitda() -> None:
    from app.agents.valuation_helpers.ev_ebitda import compute_ev_ebitda_value
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError

    with pytest.raises(InsufficientDataForModelError):
        compute_ev_ebitda_value(
            ebitda=0,
            net_debt=0,
            shares_outstanding=10e8,
            industry_ev_ebitda_avg=10.0,
            industry_ev_ebitda_median=10.0,
        )


def test_ev_ebitda_raises_for_zero_shares() -> None:
    from app.agents.valuation_helpers.ev_ebitda import compute_ev_ebitda_value
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError

    with pytest.raises(InsufficientDataForModelError):
        compute_ev_ebitda_value(
            ebitda=100e8,
            net_debt=0,
            shares_outstanding=0,
            industry_ev_ebitda_avg=10.0,
            industry_ev_ebitda_median=10.0,
        )


def test_ev_ebitda_raises_for_invalid_industry_multiple() -> None:
    from app.agents.valuation_helpers.ev_ebitda import compute_ev_ebitda_value
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError

    with pytest.raises(InsufficientDataForModelError):
        compute_ev_ebitda_value(
            ebitda=100e8,
            net_debt=0,
            shares_outstanding=10e8,
            industry_ev_ebitda_avg=0,
            industry_ev_ebitda_median=0,
        )
    # 任一为负也 raise(严格 OR guard 同 PE/PB)
    with pytest.raises(InsufficientDataForModelError):
        compute_ev_ebitda_value(
            ebitda=100e8,
            net_debt=0,
            shares_outstanding=10e8,
            industry_ev_ebitda_avg=-5.0,
            industry_ev_ebitda_median=10.0,
        )


def test_ev_ebitda_negative_implied_market_cap_clamps_zero() -> None:
    """边界:debt 远超 enterprise value → implied_market_cap < 0 → return 0.0 (不 raise)
    ev = 10e8 × 5 = 50e8, market_cap = 50e8 - 1000e8 = -950e8 → clamp 0
    """
    from app.agents.valuation_helpers.ev_ebitda import compute_ev_ebitda_value

    price = compute_ev_ebitda_value(
        ebitda=10e8,
        net_debt=1000e8,
        shares_outstanding=10e8,
        industry_ev_ebitda_avg=5.0,
        industry_ev_ebitda_median=5.0,
    )
    assert price == 0.0


def test_ev_ebitda_negative_net_debt_is_valid() -> None:
    """net_debt < 0 (净现金) 不 raise — 茅台 case 必须 work."""
    from app.agents.valuation_helpers.ev_ebitda import compute_ev_ebitda_value

    # 普通正 EBITDA + 大量净现金 → 高 implied price,合理
    price = compute_ev_ebitda_value(
        ebitda=100e8,
        net_debt=-500e8,
        shares_outstanding=10e8,
        industry_ev_ebitda_avg=10.0,
        industry_ev_ebitda_median=10.0,
    )
    assert price > 0  # market_cap = 1000e8 + 500e8 = 1500e8, price = 150


def test_ev_ebitda_raises_on_nan_input() -> None:
    """NaN 任一输入 → raise."""
    from app.agents.valuation_helpers.ev_ebitda import compute_ev_ebitda_value
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError

    with pytest.raises(InsufficientDataForModelError):
        compute_ev_ebitda_value(
            ebitda=math.nan,
            net_debt=0,
            shares_outstanding=10e8,
            industry_ev_ebitda_avg=10.0,
            industry_ev_ebitda_median=10.0,
        )
    # net_debt 是 NaN 也 raise(算 implied_market_cap 时 NaN 污染)
    with pytest.raises(InsufficientDataForModelError):
        compute_ev_ebitda_value(
            ebitda=100e8,
            net_debt=math.nan,
            shares_outstanding=10e8,
            industry_ev_ebitda_avg=10.0,
            industry_ev_ebitda_median=10.0,
        )


def test_ev_ebitda_raises_on_inf_input() -> None:
    from app.agents.valuation_helpers.ev_ebitda import compute_ev_ebitda_value
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError

    with pytest.raises(InsufficientDataForModelError):
        compute_ev_ebitda_value(
            ebitda=math.inf,
            net_debt=0,
            shares_outstanding=10e8,
            industry_ev_ebitda_avg=10.0,
            industry_ev_ebitda_median=10.0,
        )
