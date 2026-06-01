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
    """C23 regression: 样本 CV 略过 15% 阈值 → moderate (样本方差 n-1)。

    对 2 个对称值, 样本 std = |a - b| / sqrt(2)。取 sample CV=15.5%(略高于 15%
    阈值,避开恰在边界时 `cv < 0.15` 的浮点不确定),验证归属 moderate 而非 consistent。
    """
    import math

    from app.agents.valuation_helpers.consistency import analyze_consistency

    # mean=1000, sample CV=15.5% → sample_std=155, d = std*sqrt(2) (2 对称值)
    d = 155 * math.sqrt(2)
    v1 = 1000.0 - d / 2
    v2 = 1000.0 + d / 2
    result = analyze_consistency({"pe": v1, "dcf_base": v2})
    assert result == "moderate"


def test_consistency_threshold_boundary_30pct() -> None:
    """C23 regression: 样本 CV 略过 30% 阈值 → severe (样本方差 n-1)。

    取 sample CV=30.5%(略高于 30% 阈值,避开浮点边界不确定),验证归 severe。
    """
    import math

    from app.agents.valuation_helpers.consistency import analyze_consistency

    # mean=1000, sample CV=30.5% → sample_std=305, d = std*sqrt(2)
    d = 305 * math.sqrt(2)
    v1 = 1000.0 - d / 2
    v2 = 1000.0 + d / 2
    result = analyze_consistency({"pe": v1, "dcf_base": v2})
    assert result == "severe"


def test_consistency_ignores_nan_inf_values() -> None:
    """NaN / inf entry 忽略,不污染 CV(防上游 helper bug 透传)"""
    from app.agents.valuation_helpers.consistency import analyze_consistency

    # nan + inf 都被剔除,剩 pe+dcf 真有效 → consistent
    result = analyze_consistency(
        {"pe": 1500, "pb": math.nan, "ev_ebitda": math.inf, "dcf_base": 1600}
    )
    assert result == "consistent"


def test_consistency_c23_population_vs_sample_reclassification() -> None:
    """C23 regression: pe=880, dcf=1120 — population CV≈12% (consistent) but
    sample CV≈17% (moderate). After fix should be 'moderate'."""
    from app.agents.valuation_helpers.consistency import analyze_consistency

    # pop_std = sqrt(((880-1000)^2 + (1120-1000)^2) / 2) = sqrt(14400) = 120 → pop_CV=12%
    # sample_std = sqrt(((880-1000)^2 + (1120-1000)^2) / 1) = sqrt(28800) ≈ 169.7 → CV≈17%
    result = analyze_consistency({"pe": 880.0, "dcf_base": 1120.0})
    assert result == "moderate", (
        "C23: 2-lens divergence near 15% boundary must use sample variance; "
        "pe=880/dcf=1120 should be 'moderate' not 'consistent'"
    )


def test_consistency_only_one_valid_after_filter_returns_none() -> None:
    """zero/nan filter 后只剩 1 valid → None(无 cross-check)"""
    from app.agents.valuation_helpers.consistency import analyze_consistency

    result = analyze_consistency({"pe": 1500, "pb": 0, "ev_ebitda": math.nan})
    assert result is None
