"""Unit tests for app.skills.financial_research loader."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

import yaml
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


def test_composed_sop_preserves_methodology_order() -> None:
    """``composed_sop()`` 必须按 ``_METHODOLOGY_ORDER`` 顺序拼接 (solvency → ... → decision_framework),
    而不是 alphabetic 或文件系统返回顺序 — Analyst/Writer prompt 依赖此进展逻辑."""
    bundle = load_skill()
    sop = bundle.composed_sop()
    # solvency 章节 (§ 1.1) 必须在 profitability (§ 1.2) 之前.
    assert sop.index("§ 1.1") < sop.index("§ 1.2")
    # 现金流质量 (§ 1.4) 必须在 valuation (§ 2.1) 之前.
    assert sop.index("§ 1.4") < sop.index("§ 2.1")
    # 决策框架 (§ 4) 必须在最后 — 验证它出现在文档最后 5K 字符内.
    assert "§ 4" in sop[-5000:]


def test_skill_manifest_yaml_front_matter() -> None:
    """SKILL.md YAML front-matter 必须含 6 必填 field, ``component_count`` 跟实际加载 component 数对齐."""
    skill_md = Path(__file__).parent.parent.parent.parent / "app/skills/financial_research/SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    # YAML front-matter 在头部 --- ... --- 之间.
    assert text.startswith("---\n"), "SKILL.md must start with YAML front-matter"
    end = text.find("\n---\n", 4)
    assert end > 0, "SKILL.md YAML front-matter not closed"
    front_matter = yaml.safe_load(text[4:end])

    required_fields = {
        "name",
        "description",
        "version",
        "trigger",
        "loaded_by",
        "component_count",
    }
    missing = required_fields - set(front_matter.keys())
    assert not missing, f"missing fields: {missing}"
    assert front_matter["name"] == "financial_research"
    assert front_matter["version"] == "0.8.5"

    # component_count 必须跟实际 loaded 一致 (11 methodology + 3 references + 3 scripts = 17).
    bundle = load_skill()
    actual_count = (
        len(bundle.methodology) + len(bundle.references) + 3  # 3 helpers in scripts namespace
    )
    assert front_matter["component_count"] == actual_count, (
        f"component_count drift: manifest says {front_matter['component_count']}, "
        f"actual={actual_count}"
    )
