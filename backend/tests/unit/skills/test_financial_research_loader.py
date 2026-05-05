"""Unit tests for app.skills.financial_research loader."""

from __future__ import annotations

from types import ModuleType

from app.skills.financial_research import SkillBundle, load_skill


def test_load_skill_returns_bundle() -> None:
    """``load_skill()`` returns a ``SkillBundle`` with 3 attributes."""
    bundle = load_skill()
    assert isinstance(bundle, SkillBundle)
    assert isinstance(bundle.methodology, dict)
    assert isinstance(bundle.references, dict)
    assert isinstance(bundle.scripts, ModuleType)


def test_methodology_contains_11_files() -> None:
    """All 11 expected methodology files load with the right names."""
    bundle = load_skill()
    expected = {
        "solvency",
        "profitability",
        "growth",
        "cashflow_quality",
        "valuation",
        "industry",
        "shareholder_governance",
        "short_term_capital_flow",
        "event_driven",
        "risk_factors",
        "decision_framework",
    }
    assert set(bundle.methodology.keys()) == expected


def test_methodology_files_non_empty() -> None:
    """Each methodology markdown is at least 150 characters (plan acceptance)."""
    bundle = load_skill()
    for name, text in bundle.methodology.items():
        assert len(text) >= 150, f"{name} too short: {len(text)} chars"


def test_references_contain_3_files() -> None:
    """All 3 expected reference names load successfully."""
    bundle = load_skill()
    expected = {"industry_benchmarks", "recommendation_rules", "position_size_rules"}
    assert set(bundle.references.keys()) == expected


def test_industry_benchmarks_has_default_fallback() -> None:
    """``industry_benchmarks`` JSON includes the ``DEFAULT`` fallback key."""
    bundle = load_skill()
    assert "DEFAULT" in bundle.references["industry_benchmarks"]
    default_profile = bundle.references["industry_benchmarks"]["DEFAULT"]
    assert "ROE_行业平均" in default_profile
    assert "资产负债率_健康" in default_profile


def test_scripts_namespace_exposes_3_helpers() -> None:
    """The scripts ModuleType exposes the 3 deterministic helper names."""
    bundle = load_skill()
    assert hasattr(bundle.scripts, "classify_recommendation")
    assert hasattr(bundle.scripts, "compute_position_size_pct")
    assert hasattr(bundle.scripts, "lookup_industry_benchmark")


def test_composed_sop_returns_concatenated_string() -> None:
    """``composed_sop()`` concatenates all 11 markdowns and contains 7 dimension keywords."""
    bundle = load_skill()
    sop = bundle.composed_sop()
    assert isinstance(sop, str)
    assert len(sop) > 1500
    for keyword in ("偿债", "盈利", "成长", "估值", "行业", "风险", "决策"):
        assert keyword in sop, f"keyword missing from composed SOP: {keyword}"


def test_load_skill_idempotent() -> None:
    """Two ``load_skill()`` calls return bundles pointing at the same data."""
    a = load_skill()
    b = load_skill()
    # Same underlying dict objects (module-level singletons).
    assert a.methodology is b.methodology
    assert a.references is b.references
    assert a.scripts is b.scripts
