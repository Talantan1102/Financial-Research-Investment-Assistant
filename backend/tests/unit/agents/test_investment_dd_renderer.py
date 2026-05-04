"""Unit tests for investment_dd_renderer (v0.8.4)."""

from __future__ import annotations

from app.agents.investment_dd_renderer import (
    _RECOMMENDATION_ZH,
    _RISK_LEVEL_ZH,
    _SEVERITY_ZH,
    render_investment_dd_report_markdown,
)
from app.agents.investment_dd_schema import (
    InvestmentRecommendation,
    RiskAssessment,
    RiskItem,
)

from tests.fixtures.investment_dd_fixtures import minimal_valid_report


def test_renders_all_six_sections() -> None:
    report = minimal_valid_report()
    md = render_investment_dd_report_markdown(report)
    assert "# 投资标的尽调报告 — 贵州茅台酒股份有限公司 (600519.SH)" in md
    assert "## § 1 标的基本信息" in md
    assert "## § 2 主体资格" in md
    assert "## § 3 财务分析" in md
    assert "## § 4 行业分析" in md
    assert "## § 5 风险评估" in md
    assert "## § 6 投资建议" in md


def test_disclaimer_appears_top_and_bottom() -> None:
    report = minimal_valid_report()
    md = render_investment_dd_report_markdown(report)
    # Top disclaimer block
    assert md.startswith("> ⚠️"), f"Markdown must start with disclaimer block, got: {md[:60]!r}"
    # Bottom footer disclaimer
    assert "免责声明" in md
    # Appears at least twice (top + bottom)
    assert md.count("⚠️") >= 2


def test_evidence_footnotes_rendered() -> None:
    report = minimal_valid_report()
    md = render_investment_dd_report_markdown(report)
    # Fixture uses chunk_ids like maotai_2024::0 ... maotai_2024::5
    assert "[^maotai_2024::0]" in md, "Inline footnote ref must appear in markdown"
    assert "引用来源" in md, "Footnote defs section must appear"
    # At least one footnote definition line
    assert "[^maotai_2024::5]: maotai_2024::5" in md


def test_recommendation_label_zh() -> None:
    report = minimal_valid_report()
    md = render_investment_dd_report_markdown(report)
    # Fixture uses recommend_overweight
    assert "增持" in md


def test_recommendation_zh_covers_all_literals() -> None:
    """_RECOMMENDATION_ZH must cover every Literal value."""
    from typing import get_args

    field = InvestmentRecommendation.model_fields["recommendation"]
    literal_values = set(get_args(field.annotation))
    assert literal_values == set(_RECOMMENDATION_ZH.keys()), (
        f"_RECOMMENDATION_ZH out of sync: "
        f"missing={literal_values - set(_RECOMMENDATION_ZH.keys())}, "
        f"extra={set(_RECOMMENDATION_ZH.keys()) - literal_values}"
    )


def test_risk_level_zh_covers_all_literals() -> None:
    from typing import get_args

    field = RiskAssessment.model_fields["overall_risk_level"]
    literal_values = set(get_args(field.annotation))
    assert literal_values == set(_RISK_LEVEL_ZH.keys())


def test_severity_zh_covers_all_literals() -> None:
    from typing import get_args

    field = RiskItem.model_fields["severity"]
    literal_values = set(get_args(field.annotation))
    assert literal_values == set(_SEVERITY_ZH.keys())
