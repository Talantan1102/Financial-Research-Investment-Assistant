"""Unit tests for investment_dd_renderer (v0.8.4).

去推荐改造(2026-06-04):§ 6 标题由 "投资建议" 改为 "综合研判",
渲染 narrative / valuation_context / key_judgment_factors / bull/bear,
不再渲染评级 label(_RECOMMENDATION_ZH 已下线)。
"""

from __future__ import annotations

from app.agents.investment_dd_renderer import (
    _RISK_LEVEL_ZH,
    _SEVERITY_ZH,
    render_investment_dd_report_markdown,
)
from app.agents.investment_dd_schema import (
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
    # 去推荐:§ 6 由 "投资建议" 改为 "综合研判"
    assert "## § 6 综合研判" in md
    assert "## § 6 投资建议" not in md


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


def test_synthesis_renders_two_sided_and_judgment_factors() -> None:
    """综合研判:多空两面 + 估值背景 + 关键判断变量,不出现买卖评级 / 目标价。"""
    report = minimal_valid_report()
    md = render_investment_dd_report_markdown(report)
    # narrative 出现
    assert report.investment_synthesis.narrative in md
    # 多空两面 section
    assert "看多论据(Bull)" in md
    assert "看空论据(Bear)" in md
    # 估值背景 + 关键判断变量
    assert "估值研判" in md
    assert "关键判断变量" in md
    assert "高端白酒需求景气度" in md
    # 去推荐:不渲染买卖评级 label
    assert "增持" not in md
    assert "买入" not in md


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


def test_includes_metric_table() -> None:
    from app.agents.investment_dd_schema import FinancialMetric

    report = minimal_valid_report()
    report.financial_analysis.key_metrics = [
        FinancialMetric(name="营业收入", value="819 亿元", period="2024 H1", yoy_change="+17%"),
    ]
    md = render_investment_dd_report_markdown(report)
    assert "营业收入" in md
    assert "819 亿元" in md


def test_idempotent() -> None:
    report = minimal_valid_report()
    assert render_investment_dd_report_markdown(report) == render_investment_dd_report_markdown(
        report
    )


def test_empty_key_metrics_renders_placeholder() -> None:
    """FinancialAnalysis.key_metrics=[] should render a placeholder, not crash."""
    report = minimal_valid_report()
    report.financial_analysis.key_metrics = []
    md = render_investment_dd_report_markdown(report)
    assert "_暂无关键财务指标_" in md
    assert "## § 3 财务分析" in md


def test_includes_evidence_footnotes_per_section() -> None:
    """Evidence chunk_ids from multiple sections must all appear as footnotes."""
    report = minimal_valid_report()
    md = render_investment_dd_report_markdown(report)
    # Fixture uses maotai_2024::0 ... maotai_2024::5 across 6 sections
    assert "maotai_2024::0" in md
    assert "maotai_2024::5" in md


def test_disclaimer_appears_in_output() -> None:
    """Disclaimer text must contain both 'AI 模型' and '投资决策'."""
    md = render_investment_dd_report_markdown(minimal_valid_report())
    assert "AI 模型" in md
    assert "投资决策" in md


# ── C48: duplicate footnote dedup ────────────────────────────────────────────


def test_no_duplicate_footnote_definitions_when_same_chunk_cited_in_multiple_sections() -> None:
    """C48: a chunk_id cited in two sections must produce exactly one [^id]: definition."""
    report = minimal_valid_report()
    # Override evidence so two sections share the same chunk_id "shared_chunk::0"
    report.target_overview.evidence = ["shared_chunk::0"]
    report.legal_qualification.evidence = ["shared_chunk::0"]

    md = render_investment_dd_report_markdown(report)

    # Exactly one footnote definition for the shared chunk_id
    definition_line = "[^shared_chunk::0]: shared_chunk::0"
    assert md.count(definition_line) == 1, (
        f"Expected exactly 1 footnote definition for shared_chunk::0, "
        f"got {md.count(definition_line)}"
    )


def test_multiple_unique_footnotes_all_present() -> None:
    """C48: unique chunk_ids from multiple sections are all emitted once."""
    report = minimal_valid_report()
    md = render_investment_dd_report_markdown(report)
    # Fixture uses maotai_2024::0 through ::5 in different sections
    for i in range(6):
        definition = f"[^maotai_2024::{i}]: maotai_2024::{i}"
        assert md.count(definition) == 1, f"Expected exactly 1 definition for maotai_2024::{i}"
