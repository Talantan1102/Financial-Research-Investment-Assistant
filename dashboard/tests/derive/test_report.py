"""研究报告 loader 单测 — load + 类型化 + fail-loud + 可读性守卫。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from dashboard.derive.report import Report, load_report

REPORTS_DIR = Path(__file__).parent.parent.parent / "data" / "reports"
DD_REPORT = REPORTS_DIR / "deep-research-report-eval.yaml"


@pytest.fixture
def dd_report() -> Report:
    return load_report(DD_REPORT)


def test_loads_dd_report_meta(dd_report: Report) -> None:
    assert dd_report.slug == "deep-research-report-eval"
    assert "深度研报" in dd_report.title
    assert dd_report.summary
    assert dd_report.date == "2026-06-02"


def test_seven_dimensions_each_has_full_example(dd_report: Report) -> None:
    """7 个评估维度,每个都带完整 worked example(setup/question/good/bad/scored)。"""
    assert len(dd_report.dimensions) == 7
    for d in dd_report.dimensions:
        assert d.name and d.plain
        assert d.setup and d.question
        assert d.good and d.bad and d.scored
    names = " ".join(d.name for d in dd_report.dimensions)
    assert "忠实度" in names
    assert "引用" in names
    assert "预测可回测" in names
    assert "LLM-as-Judge" in names or "LLM-as-judge" in names


def test_benchmarks_gaps_map_to_project_metrics(dd_report: Report) -> None:
    assert any("RAGAS" in b.name for b in dd_report.benchmarks)
    assert any("DeepResearch Bench" in b.name for b in dd_report.benchmarks)
    assert len(dd_report.pitfalls) >= 5
    # 对照本项目 5 把尺子 + 整体框架 —— 用白话名(不再用 M1/M2 内部代号)
    components = " ".join(g.component for g in dd_report.gaps)
    for label in ("引用抽取", "数值核对", "风险与缓解", "预测回测", "评委", "整体评估"):
        assert label in components, f"缺对照:{label}"
    # 来源带真实 URL
    assert all(s.url.startswith("http") for s in dd_report.sources)
    assert any("arxiv.org/abs/2506.11763" in s.url for s in dd_report.sources)


def test_report_has_no_opaque_codes(dd_report: Report) -> None:
    """可读性守卫:正文不出现 M1–M5 内部代号和最难懂的裸缩写(MAFE/MAPE/NLI/F1@K)。"""
    blob = " ".join(
        [dd_report.subtitle, dd_report.summary]
        + [f"{d.good} {d.bad} {d.scored} {d.plain}" for d in dd_report.dimensions]
        + [g.component + g.current + g.suggestion for g in dd_report.gaps]
        + list(dd_report.pitfalls)
    )
    assert not re.search(r"\bM[1-5]\b", blob), "正文仍有 M1–M5 内部代号"
    for code in ("MAFE", "MAPE", "F1@K", "macro-F1", " NLI", "F-β"):
        assert code not in blob, f"正文仍有裸缩写: {code.strip()}"


def test_missing_dimension_field_fails_loud(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        """
slug: x
title: T
summary: s
dimensions:
  - name: 维度一
    plain: p
    setup: s
    question: q
    good: g
    bad: b
""",  # 缺 scored
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="dimensions.*scored"):
        load_report(bad)


def test_missing_required_top_level_fails_loud(tmp_path: Path) -> None:
    bad = tmp_path / "bad2.yaml"
    bad.write_text("slug: x\ntitle: T\n", encoding="utf-8")  # 缺 summary + dimensions
    with pytest.raises(ValueError):
        load_report(bad)
