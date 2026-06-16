"""Chat Runtime 优化地图研报的 loader / 可读性 / 端点 / 体裁标签测试。

「调研/综述」体裁(代码审读 × 工业界调研对照),与 chat-agent-loop-survey 同构:
dimensions_meta / benchmarks_title 自定义区标题与行标签,归「生命周期」维度页
(/m/lifecycle),不挂评估页 /eval。纯净增文件,不碰 main 既有测试。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from dashboard.derive.report import Report, load_report

REPORTS_DIR = Path(__file__).parent.parent.parent / "data" / "reports"
RUNTIME_REPORT = REPORTS_DIR / "chatloop-runtime-optimization-survey.yaml"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    from dashboard import server

    monkeypatch.setattr(server, "DB_PATH", tmp_path / "board.db")
    return TestClient(server.app)


@pytest.fixture
def report() -> Report:
    return load_report(RUNTIME_REPORT)


# ---- loader / 内容完整性 ----------------------------------------------------


def test_meta_and_dimensions(report: Report) -> None:
    assert report.slug == "chatloop-runtime-optimization-survey"
    assert "Runtime" in report.title and "工业界" in report.title
    assert report.date == "2026-06-10"
    # 7 个运行时优化决策,每个 worked example 字段齐全
    assert len(report.dimensions) == 7
    for d in report.dimensions:
        assert d.name and d.plain and d.setup and d.question and d.good and d.bad and d.scored
    names = " ".join(d.name for d in report.dimensions)
    # 覆盖上下文压缩 / 工具体积 / 超时 / 终止闸 / 插话 / 子 agent / 度量
    assert "压缩" in names and "体积" in names and "超时" in names
    assert "终止闸" in names and "插话" in names and "子 agent" in names and "度量" in names


def test_our_problems_carry_file_line_evidence(report: Report) -> None:
    """本报告的差异化约定:「我们的问题」一栏必须落到 file:line 证据。"""
    file_line = re.compile(r"\w+\.py:\d+")
    for d in report.dimensions:
        assert file_line.search(d.question), f"{d.name} 的问题描述缺 file:line 证据"


def test_survey_genre_labels(report: Report) -> None:
    """调研体裁:区标题与行标签被 dimensions_meta / benchmarks_title 覆盖。"""
    assert "7 个运行时优化决策" in report.dim_labels.section_title
    assert report.dim_labels.setup == "场景"
    assert report.dim_labels.question == "我们的问题"
    assert report.dim_labels.good == "工业界做法"
    assert report.dim_labels.bad == "翻车点"
    # 评估体裁的默认词不应泄漏到这份报告的标签里
    assert report.dim_labels.scored != "怎么判分"
    assert "runtime" in report.benchmarks_title


def test_benchmarks_and_gaps(report: Report) -> None:
    bnames = " ".join(b.name for b in report.benchmarks)
    assert "OpenAI Agents SDK" in bnames and "Claude Code" in bnames
    assert "LangGraph" in bnames and "Manus" in bnames and "Anthropic" in bnames
    assert len(report.pitfalls) >= 5
    # 对照本项目:gaps 指向真实 chatloop 组件
    comps = " ".join(g.component for g in report.gaps)
    assert "上下文" in comps and "工具" in comps and "终止闸" in comps
    assert "steering" in comps and "度量" in comps


def test_sources_are_http_and_cover_key_refs(report: Report) -> None:
    assert report.sources
    assert all(s.url.startswith("http") for s in report.sources)
    urls = " ".join(s.url for s in report.sources)
    # Manus context engineering + Anthropic compaction + Claude Code steering 文档
    assert "manus.im/blog" in urls
    assert "platform.claude.com/docs" in urls
    assert "code.claude.com/docs" in urls
    assert "openai.github.io" in urls


# ---- 可读性守卫:正文不得含读者无法对应的字母数字代号 ------------------------

_OPAQUE = [
    re.compile(r"(?<![A-Za-z$])S\d"),
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


# ---- 端点:报告页渲染 + 维度页列表(不挂评估页)-----------------------------


def test_lifecycle_dimension_page_lists_runtime_report(client: TestClient) -> None:
    page = client.get("/m/lifecycle").text
    assert 'href="/eval/report/chatloop-runtime-optimization-survey"' in page
    assert "Runtime 优化地图" in page
    # 评估页不应列这份调研报告(它不是评估方法论)
    eval_body = client.get("/eval").text
    assert "chatloop-runtime-optimization-survey" not in eval_body


def test_runtime_report_page_renders(client: TestClient) -> None:
    resp = client.get("/eval/report/chatloop-runtime-optimization-survey")
    assert resp.status_code == 200
    body = resp.text
    # 内容关键点:工业界机制 + 我们的 file:line 证据
    assert "compaction" in body and "max_turns" in body
    assert "tool_hub.py" in body and "gates.py" in body
    # 调研体裁标签已生效,评估体裁默认词不应出现
    assert "我们的问题" in body and "工业界做法" in body and "翻车点" in body
    assert "7 个运行时优化决策" in body
    assert "怎么判分" not in body
    # 来源可点 + 返回链接
    assert "manus.im/blog" in body
    assert 'href="/eval"' in body
