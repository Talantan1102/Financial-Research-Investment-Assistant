"""chat 模式 agent loop 调研研报的 loader / 可读性 / 端点 / 体裁标签测试。

这份是「调研/综述」体裁(非「评估」体裁),用 report.py 的 dimensions_meta /
benchmarks_title 自定义区标题与行标签,与 subagent-dispatch-survey 同构。
归到「生命周期」维度页(/m/lifecycle),不挂在评估页 /eval。纯净增文件,不碰
main 既有测试。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from dashboard.derive.report import Report, load_report

REPORTS_DIR = Path(__file__).parent.parent.parent / "data" / "reports"
LOOP_REPORT = REPORTS_DIR / "chat-agent-loop-survey.yaml"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    from dashboard import server

    monkeypatch.setattr(server, "DB_PATH", tmp_path / "board.db")
    return TestClient(server.app)


@pytest.fixture
def report() -> Report:
    return load_report(LOOP_REPORT)


# ---- loader / 内容完整性 ----------------------------------------------------


def test_meta_and_dimensions(report: Report) -> None:
    assert report.slug == "chat-agent-loop-survey"
    assert "Loop" in report.title and "怎么做" in report.title
    assert report.date == "2026-06-03"
    # 7 个 chat-loop 设计决策,每个 worked example 字段齐全
    assert len(report.dimensions) == 7
    for d in report.dimensions:
        assert d.name and d.plain and d.setup and d.question and d.good and d.bad and d.scored
    names = " ".join(d.name for d in report.dimensions)
    # 覆盖循环骨架 / workflow-vs-agent / 终止 / 上下文 / 流式 / 人在环 / 自纠
    assert "循环骨架" in names and "workflow" in names and "终止" in names
    assert "上下文" in names and "流式" in names and "人在环" in names and "自纠" in names


def test_survey_genre_labels(report: Report) -> None:
    """调研体裁:区标题与行标签被 dimensions_meta / benchmarks_title 覆盖。"""
    assert report.dim_labels.section_title == "7 个 chat-loop 设计决策 · 每个配一个真实场景"
    assert report.dim_labels.setup == "场景"
    assert report.dim_labels.good == "好做法"
    assert report.dim_labels.bad == "翻车点"
    # 评估体裁的默认词不应泄漏到这份报告的标签里
    assert report.dim_labels.scored != "怎么判分"
    assert report.benchmarks_title == "代表系统 / 方法 · 循环机制速览"


def test_benchmarks_and_gaps(report: Report) -> None:
    bnames = " ".join(b.name for b in report.benchmarks)
    assert "ReAct" in bnames and "12-Factor" in bnames and "Reflexion" in bnames
    assert "OpenAI Agents SDK" in bnames and "LangGraph" in bnames
    assert len(report.pitfalls) >= 5
    # 对照本项目:gaps 指向真实 chat 循环组件
    comps = " ".join(g.component for g in report.gaps)
    assert "循环骨架" in comps and "上下文" in comps and "人在环" in comps


def test_sources_are_http_and_cover_key_refs(report: Report) -> None:
    assert report.sources
    assert all(s.url.startswith("http") for s in report.sources)
    urls = " ".join(s.url for s in report.sources)
    # ReAct + Reflexion 两篇关键论文 + Anthropic 工程博客
    assert "arxiv.org/abs/2210.03629" in urls
    assert "arxiv.org/abs/2303.11366" in urls
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


# ---- 端点:报告页渲染 + 维度页列表(不挂评估页)-----------------------------


def test_lifecycle_dimension_page_lists_loop_report(client: TestClient) -> None:
    """调研体裁:agent loop 报告归到「生命周期」维度页(/m/lifecycle),不在评估页 /eval。"""
    page = client.get("/m/lifecycle").text
    assert 'href="/eval/report/chat-agent-loop-survey"' in page
    assert "Agent Loop" in page
    assert "深度调研" in page
    # 评估页不应列这份调研报告(它不是评估方法论)
    eval_body = client.get("/eval").text
    assert "chat-agent-loop-survey" not in eval_body


def test_loop_report_page_renders(client: TestClient) -> None:
    resp = client.get("/eval/report/chat-agent-loop-survey")
    assert resp.status_code == 200
    body = resp.text
    # 内容关键点
    assert "ReAct" in body and "12-Factor" in body and "Reflexion" in body
    assert "max_turns" in body and "recursion_limit" in body
    # 调研体裁标签已生效(自定义行标签 + 区标题),评估体裁默认词不应出现
    assert "场景" in body and "好做法" in body and "翻车点" in body
    assert "7 个 chat-loop 设计决策" in body
    assert "评估维度" not in body
    assert "怎么判分" not in body
    # 来源可点 + 返回链接
    assert "arxiv.org/abs/2210.03629" in body
    assert 'href="/eval"' in body
