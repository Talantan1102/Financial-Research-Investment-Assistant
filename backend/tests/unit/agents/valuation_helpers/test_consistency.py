"""L0 — cross-check consistency analyzer."""

from __future__ import annotations

import math


def test_consistency_single_lens_returns_none() -> None:
    from app.agents.valuation_helpers.consistency import analyze_consistency

    assert analyze_consistency({"pe": 1500}) is None
    assert analyze_consistency({}) is None


def test_consistency_two_lens_consistent() -> None:
    """pe=1500, dcf=1600 → CV ≈ 3.2% < 15%"""
    from app.agents.valuation_helpers.consistency import analyze_consistency

    result = analyze_consistency({"pe": 1500, "dcf_base": 1600})
    assert result == "consistent"


def test_consistency_moderate_divergence() -> None:
    """pe=1200, dcf=1800 → mean=1500, std=300, CV=20% → moderate"""
    from app.agents.valuation_helpers.consistency import analyze_consistency

    result = analyze_consistency({"pe": 1200, "dcf_base": 1800})
    assert result == "moderate"


def test_consistency_severe_divergence() -> None:
    """pe=500, dcf=2000 → CV > 30% → severe"""
    from app.agents.valuation_helpers.consistency import analyze_consistency

    result = analyze_consistency({"pe": 500, "dcf_base": 2000})
    assert result == "severe"


def test_consistency_four_lens_consistent() -> None:
    """4 lens 接近 → consistent"""
    from app.agents.valuation_helpers.consistency import analyze_consistency

    result = analyze_consistency({"pe": 1500, "pb": 1550, "ev_ebitda": 1480, "dcf_base": 1600})
    assert result == "consistent"


def test_consistency_ignores_zero_values() -> None:
    """0(clamp 后的 EV/EBITDA)忽略,不算入 CV"""
    from app.agents.valuation_helpers.consistency import analyze_consistency

    # 只有 pe + dcf 真有效 → 同 two_lens_consistent
    result = analyze_consistency({"pe": 1500, "pb": 0, "dcf_base": 1600})
    assert result == "consistent"


def test_consistency_threshold_boundary_15pct() -> None:
    """边界:CV = 15.0% → 取 ">= 0.15" 严格归 moderate"""
    from app.agents.valuation_helpers.consistency import analyze_consistency

    # mean=1000, std=150 → CV=15%
    # 构造 [850, 1150]: mean=1000, var=((850-1000)^2 + (1150-1000)^2)/2=22500, std=150
    result = analyze_consistency({"pe": 850.0, "dcf_base": 1150.0})
    assert result == "moderate"


def test_consistency_threshold_boundary_30pct() -> None:
    """边界:CV = 30.0% → 取 ">= 0.30" 严格归 severe"""
    from app.agents.valuation_helpers.consistency import analyze_consistency

    # mean=1000, std=300 → CV=30%
    result = analyze_consistency({"pe": 700.0, "dcf_base": 1300.0})
    assert result == "severe"


def test_consistency_ignores_nan_inf_values() -> None:
    """NaN / inf entry 忽略,不污染 CV(防上游 helper bug 透传)"""
    from app.agents.valuation_helpers.consistency import analyze_consistency

    # nan + inf 都被剔除,剩 pe+dcf 真有效 → consistent
    result = analyze_consistency(
        {"pe": 1500, "pb": math.nan, "ev_ebitda": math.inf, "dcf_base": 1600}
    )
    assert result == "consistent"


def test_consistency_only_one_valid_after_filter_returns_none() -> None:
    """zero/nan filter 后只剩 1 valid → None(无 cross-check)"""
    from app.agents.valuation_helpers.consistency import analyze_consistency

    result = analyze_consistency({"pe": 1500, "pb": 0, "ev_ebitda": math.nan})
    assert result is None
