"""verl 多步工具 RL 施工配方研报的 loader / 图例 / 可读性 / 端点 / 体裁测试。

RL 三部曲第二部(施工/how-to 体裁),挂工具维度页(/m/tool)。带 3 张图例,
服务端 include 内联。纯净增文件。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from dashboard.derive.report import Report, load_report

REPORTS_DIR = Path(__file__).parent.parent.parent / "data" / "reports"
FIGURES_DIR = Path(__file__).parent.parent.parent / "templates" / "figures"
VERL_REPORT = REPORTS_DIR / "verl-multistep-tool-rl.yaml"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    from dashboard import server

    monkeypatch.setattr(server, "DB_PATH", tmp_path / "board.db")
    return TestClient(server.app)


@pytest.fixture
def report() -> Report:
    return load_report(VERL_REPORT)


# ---- loader / 内容完整性 ----------------------------------------------------


def test_meta_and_dimensions(report: Report) -> None:
    assert report.slug == "verl-multistep-tool-rl"
    assert "verl" in report.title and "施工" in report.title
    assert report.date == "2026-06-09"
    assert len(report.dimensions) == 7
    for d in report.dimensions:
        assert d.name and d.plain and d.setup and d.question and d.good and d.bad and d.scored
    names = " ".join(d.name for d in report.dimensions)
    assert "多轮路径" in names and "oracle" in names and "masking" in names
    assert "credit" in names and "重要性采样" in names and "可重放" in names


def test_survey_genre_labels(report: Report) -> None:
    assert report.dim_labels.section_title == "7 个施工决策 · 每个配一个真实落点"
    assert report.dim_labels.setup == "场景"
    assert report.dim_labels.good == "好做法"
    assert report.dim_labels.bad == "翻车点"
    assert report.dim_labels.scored != "怎么判分"
    assert report.benchmarks_title == "工具-RL 先例 · 可借做法速览"


def test_figures_declared_and_files_exist(report: Report) -> None:
    figures = [s.figure for s in report.sections if s.figure]
    assert len(figures) == 3
    assert "verl-task-mapping.svg" in figures
    assert "verl-oracle-reward-flow.svg" in figures
    assert "verl-pitfall-map.svg" in figures
    for s in report.sections:
        if s.figure:
            svg = FIGURES_DIR / s.figure
            assert svg.is_file(), f"图例文件缺失: {s.figure}"
            assert "<svg" in svg.read_text(encoding="utf-8")
            assert s.figure_caption, f"图例缺 caption: {s.figure}"


def test_benchmarks_and_gaps(report: Report) -> None:
    bnames = " ".join(b.name for b in report.benchmarks)
    assert "金融问答 RL" in bnames and "检索增强 RL" in bnames and "代码工具 RL" in bnames
    assert len(report.pitfalls) >= 8
    comps = " ".join(g.component for g in report.gaps)
    assert "oracle" in comps and "工具接入" in comps and "可重放环境" in comps


def test_sources_cover_verl_and_papers(report: Report) -> None:
    assert report.sources
    urls = " ".join(s.url for s in report.sources)
    # verl 仓库 + 文档 + HybridFlow 论文 + Search-R1 + 内部施工底稿
    assert "github.com/verl-project/verl" in urls
    assert "verl.readthedocs.io" in urls
    assert "arxiv.org/abs/2409.19256" in urls
    assert "arxiv.org/abs/2503.09516" in urls
    assert "docs/research/2026-06-09-verl-multistep-tool-rl-recipe.md" in urls


# ---- 可读性守卫 -------------------------------------------------------------

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


# ---- 端点:报告页渲染(图例内联)+ 维度页列表 ----------------------------


def test_tool_dimension_page_lists_report(client: TestClient) -> None:
    tool_body = client.get("/m/tool").text
    assert 'href="/eval/report/verl-multistep-tool-rl"' in tool_body
    assert "施工配方" in tool_body
    assert "深度调研" in tool_body
    eval_body = client.get("/eval").text
    assert "verl-multistep-tool-rl" not in eval_body


def test_report_page_renders_with_figures(client: TestClient) -> None:
    resp = client.get("/eval/report/verl-multistep-tool-rl")
    assert resp.status_code == 200
    body = resp.text
    assert "ToolAgentLoop" in body and "compute_score" in body and "loss masking" in body
    # 3 个 figure 容器,3 张 svg 命名空间前缀在场
    assert body.count('class="report-figure"') == 3
    for ns in ("vtm-", "vor-", "vpm-"):
        assert ns in body, f"图例 svg 未内联: 命名空间 {ns} 缺失"
    assert body.count('class="report-figcaption"') == 3
    assert "好做法" in body and "翻车点" in body
    assert "7 个施工决策" in body
    assert "评估维度" not in body and "怎么判分" not in body
    assert 'href="/eval"' in body
