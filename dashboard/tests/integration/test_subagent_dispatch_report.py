"""子 agent 派发调研研报的 loader / 可读性 / 端点 / 体裁标签测试。

这份是「调研/综述」体裁(非「评估」体裁),用 report.py 的 dimensions_meta /
benchmarks_title 自定义区标题与行标签。纯净增文件,不碰 main 既有测试。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from dashboard.derive.report import Report, load_report

REPORTS_DIR = Path(__file__).parent.parent.parent / "data" / "reports"
DISPATCH_REPORT = REPORTS_DIR / "subagent-dispatch-survey.yaml"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    from dashboard import server

    monkeypatch.setattr(server, "DB_PATH", tmp_path / "board.db")
    return TestClient(server.app)


@pytest.fixture
def report() -> Report:
    return load_report(DISPATCH_REPORT)


# ---- loader / 内容完整性 ----------------------------------------------------


def test_meta_and_dimensions(report: Report) -> None:
    assert report.slug == "subagent-dispatch-survey"
    assert "派发" in report.title
    assert report.date == "2026-06-03"
    # 7 个派发设计决策,每个 worked example 字段齐全
    assert len(report.dimensions) == 7
    for d in report.dimensions:
        assert d.name and d.plain and d.setup and d.question and d.good and d.bad and d.scored
    names = " ".join(d.name for d in report.dimensions)
    assert "谁来路由" in names and "并行" in names and "context 隔离" in names
    assert "结果聚合" in names and "深度与终止" in names and "模型分档" in names


def test_survey_genre_labels(report: Report) -> None:
    """调研体裁:区标题与行标签被 dimensions_meta / benchmarks_title 覆盖。"""
    assert report.dim_labels.section_title == "7 个派发设计决策 · 每个配一个真实场景"
    assert report.dim_labels.setup == "场景"
    assert report.dim_labels.good == "好的派法"
    assert report.dim_labels.bad == "翻车点"
    # 评估体裁的默认词不应泄漏到这份报告的标签里
    assert report.dim_labels.scored != "怎么判分"
    assert report.benchmarks_title == "代表性系统 · 派发机制速览"


def test_benchmarks_and_gaps(report: Report) -> None:
    bnames = " ".join(b.name for b in report.benchmarks)
    assert "Anthropic" in bnames and "MetaGPT" in bnames and "Mixture-of-Agents" in bnames
    assert len(report.pitfalls) >= 5
    # 对照本项目:gaps 指向真实编排组件
    comps = " ".join(g.component for g in report.gaps)
    assert "ChatPlanner" in comps and "辩论" in comps


def test_sources_are_http_and_cover_key_papers(report: Report) -> None:
    assert report.sources
    assert all(s.url.startswith("http") for s in report.sources)
    urls = " ".join(s.url for s in report.sources)
    # MAST 失败分类学 + Mixture-of-Agents + Anthropic 工程博客
    assert "arxiv.org/abs/2503.13657" in urls
    assert "arxiv.org/abs/2406.04692" in urls
    assert "anthropic.com/engineering" in urls


# ---- 可读性守卫:正文不得含读者无法对应的字母数字代号 ------------------------

# 与既有报告同一套黑名单:Session 缩写 S<n>、内部 golden 编号、内部指标编号、
# 占位符「正确答案 X」—— 调研体裁同样不该出现。
_OPAQUE = [
    re.compile(r"(?<![A-Za-z])S\d"),
    re.compile(r"c5-golden"),
    re.compile(r"Metric\s*\d"),
    re.compile(r"正确答案\s*X"),
]


def _report_text(r: Report) -> str:
    parts: list[str] = [r.summary]
    for s in r.sections:
        parts.append(s.heading + s.body + " ".join(s.bullets))
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


# ---- 端点:报告页渲染 + /eval 列表 ------------------------------------------


def test_tool_dimension_page_lists_dispatch_report(client: TestClient) -> None:
    """调研体裁:派发报告归到「工具」维度页(/m/tool),不再挂在评估页 /eval。"""
    tool_body = client.get("/m/tool").text
    assert 'href="/eval/report/subagent-dispatch-survey"' in tool_body
    assert "子 agent 派发" in tool_body
    assert "深度调研" in tool_body
    # 评估页不应再列这份调研报告(它不是评估方法论)
    eval_body = client.get("/eval").text
    assert "subagent-dispatch-survey" not in eval_body


def test_dispatch_report_page_renders(client: TestClient) -> None:
    resp = client.get("/eval/report/subagent-dispatch-survey")
    assert resp.status_code == 200
    body = resp.text
    # 内容关键点
    assert "Flappy Bird" in body and "Anthropic" in body and "Cognition" in body
    assert "90.2%" in body
    # 调研体裁标签已生效(自定义行标签 + 区标题),评估体裁默认词不应出现
    assert "场景" in body and "好的派法" in body and "翻车点" in body
    assert "7 个派发设计决策" in body
    assert "评估维度" not in body
    assert "怎么判分" not in body
    # 来源可点
    assert "arxiv.org/abs/2503.13657" in body
    assert 'href="/eval"' in body
