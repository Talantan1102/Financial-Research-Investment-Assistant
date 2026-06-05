"""LLM 后训练调研研报的 loader / 图例 / 可读性 / 端点 / 体裁标签测试。

「调研/综述」体裁(非「评估」体裁),挂在工具维度页(/m/tool)。本报告是首个
带图例(figure)的研报:sections 里的 svg 经 templates/figures/ server-side
include 内联渲染,测试覆盖 figure 字段校验与端点内联结果。纯净增文件。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from dashboard.derive.report import Report, load_report

REPORTS_DIR = Path(__file__).parent.parent.parent / "data" / "reports"
FIGURES_DIR = Path(__file__).parent.parent.parent / "templates" / "figures"
RL_REPORT = REPORTS_DIR / "post-training-rl-survey.yaml"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    from dashboard import server

    monkeypatch.setattr(server, "DB_PATH", tmp_path / "board.db")
    return TestClient(server.app)


@pytest.fixture
def report() -> Report:
    return load_report(RL_REPORT)


# ---- loader / 内容完整性 ----------------------------------------------------


def test_meta_and_dimensions(report: Report) -> None:
    assert report.slug == "post-training-rl-survey"
    assert "后训练" in report.title and "RL" in report.title
    assert report.date == "2026-06-05"
    # 7 个后训练设计决策,每个 worked example 字段齐全
    assert len(report.dimensions) == 7
    for d in report.dimensions:
        assert d.name and d.plain and d.setup and d.question and d.good and d.bad and d.scored
    names = " ".join(d.name for d in report.dimensions)
    assert "升级判别" in names and "算法选型" in names and "数据构造" in names
    assert "奖励设计" in names and "hacking" in names and "评估闭环" in names
    assert "verl" in names


def test_survey_genre_labels(report: Report) -> None:
    """调研体裁:区标题与行标签被 dimensions_meta / benchmarks_title 覆盖。"""
    assert report.dim_labels.section_title == "7 个后训练设计决策 · 每个配一个真实场景"
    assert report.dim_labels.setup == "场景"
    assert report.dim_labels.good == "好做法"
    assert report.dim_labels.bad == "翻车点"
    # 评估体裁的默认词不应泄漏到这份报告的标签里
    assert report.dim_labels.scored != "怎么判分"
    assert report.benchmarks_title == "代表性系统 · 后训练配方速览"


def test_figures_declared_and_files_exist(report: Report) -> None:
    """5 张图例:文件名合法、svg 实际存在、都带 caption。"""
    figures = [s.figure for s in report.sections if s.figure]
    assert len(figures) == 5
    assert "posttraining-decision-tree.svg" in figures
    assert "verl-sglang-architecture.svg" in figures
    assert "product-rl-mapping.svg" in figures
    for s in report.sections:
        if s.figure:
            svg = FIGURES_DIR / s.figure
            assert svg.is_file(), f"图例文件缺失: {s.figure}"
            assert "<svg" in svg.read_text(encoding="utf-8")
            assert s.figure_caption, f"图例缺 caption: {s.figure}"


def test_benchmarks_and_gaps(report: Report) -> None:
    bnames = " ".join(b.name for b in report.benchmarks)
    assert "DeepSeek-R1" in bnames and "Tülu 3" in bnames and "Fin-R1" in bnames
    assert "Kimi K2" in bnames and "Agent Lightning" in bnames
    assert len(report.pitfalls) >= 8
    # 对照本项目:gaps 指向真实组件,用大白话不用内部代号
    comps = " ".join(g.component for g in report.gaps)
    assert "估值数值核对" in comps and "工具调用规划" in comps
    assert "研报生成" in comps and "记忆抽取" in comps and "评估资产" in comps


def test_sources_are_http_and_cover_key_papers(report: Report) -> None:
    assert report.sources
    assert all(s.url.startswith("http") for s in report.sources)
    urls = " ".join(s.url for s in report.sources)
    # SFT vs RL 判别 + DeepSeek-R1 + HybridFlow/verl + RFT 官方
    assert "arxiv.org/abs/2501.17161" in urls
    assert "arxiv.org/abs/2501.12948" in urls
    assert "arxiv.org/abs/2409.19256" in urls
    assert "developers.openai.com" in urls
    assert "verl.readthedocs.io" in urls


# ---- 可读性守卫:正文不得含读者无法对应的字母数字代号 ------------------------

_OPAQUE = [
    re.compile(r"(?<![A-Za-z])S\d"),
    re.compile(r"c5-golden"),
    re.compile(r"Metric\s*\d"),
    re.compile(r"正确答案\s*X"),
]


def _report_text(r: Report) -> str:
    parts: list[str] = [r.summary]
    for s in r.sections:
        parts.append(s.heading + s.body + s.figure_caption + " ".join(s.bullets))
    for d in r.dimensions:
        parts.append(f"{d.name} {d.plain} {d.setup} {d.question} {d.good} {d.bad} {d.scored}")
    for b in r.benchmarks:
        parts.append(b.name + b.what + b.fit)
    parts.extend(r.pitfalls)
    for g in r.gaps:
        parts.append(g.component + g.current + g.suggestion)
    return "\n".join(parts)


def test_report_has_no_opaque_codes(report: Report) -> None:
    text = _report_text(report)
    for pat in _OPAQUE:
        m = pat.search(text)
        assert m is None, f"报告含读者无法对应的代号: {m.group(0)!r}"


def test_numbers_carry_caliber(report: Report) -> None:
    """关键数字必须带口径:抽查几处承重结论的口径标注在正文里。"""
    text = _report_text(report)
    assert "自报" in text  # 厂商自报口径标注
    assert "口径" in text
    # 蒸馏 vs 直接 RL 的对照数字 + AIME 纯 RL 数字
    assert "72.6%" in text and "47.0%" in text
    assert "15.6%" in text and "71.0%" in text
    # 吞吐区间口径(不许只写 20×)
    assert "1.53" in text and "20.57" in text


# ---- 端点:报告页渲染 + 维度页列表 ------------------------------------------


def test_tool_dimension_page_lists_rl_report(client: TestClient) -> None:
    """调研体裁:后训练报告归到「工具」维度页(/m/tool),不挂评估页 /eval。"""
    tool_body = client.get("/m/tool").text
    assert 'href="/eval/report/post-training-rl-survey"' in tool_body
    assert "后训练" in tool_body
    assert "深度调研" in tool_body
    # 评估页不应列这份调研报告(它不是评估方法论)
    eval_body = client.get("/eval").text
    assert "post-training-rl-survey" not in eval_body


def test_rl_report_page_renders_with_figures(client: TestClient) -> None:
    resp = client.get("/eval/report/post-training-rl-survey")
    assert resp.status_code == 200
    body = resp.text
    # 内容关键点
    assert "DeepSeek-R1" in body and "Tülu 3" in body and "GRPO" in body
    assert "RadixAttention" in body and "reward hacking" in body
    # 图例内联渲染:5 个 figure 容器,5 张 svg 真实内联(非 <img> 引用)。
    # 各 svg 的命名空间 class 前缀逐一在场(base 模板自带导航图标 svg,不数总量)
    assert body.count('class="report-figure"') == 5
    for ns in ("ptdt-", "rdp-", "rs-", "va-", "pm-"):
        assert ns in body, f"图例 svg 未内联: 命名空间 {ns} 缺失"
    assert body.count('class="report-figcaption"') == 5
    # 调研体裁标签生效,评估体裁默认词不出现
    assert "好做法" in body and "翻车点" in body
    assert "7 个后训练设计决策" in body
    assert "评估维度" not in body and "怎么判分" not in body
    # 来源可点
    assert "arxiv.org/abs/2501.12948" in body
    assert 'href="/eval"' in body
