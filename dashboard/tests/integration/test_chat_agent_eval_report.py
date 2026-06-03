"""对话/工具型 agent 评估研报的 loader / 可读性 / 端点测试。

这份是「评估」体裁(用 report.py 默认 worked-example 标签:铺垫→问→好答→
坏答→怎么判分),沉淀自 #118 的对话 agent 评估方法论调研。纯净增文件,
不碰 main 既有测试。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from dashboard.derive.report import Report, load_report

REPORTS_DIR = Path(__file__).parent.parent.parent / "data" / "reports"
CHAT_EVAL_REPORT = REPORTS_DIR / "chat-agent-evaluation.yaml"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    from dashboard import server

    monkeypatch.setattr(server, "DB_PATH", tmp_path / "board.db")
    return TestClient(server.app)


@pytest.fixture
def report() -> Report:
    return load_report(CHAT_EVAL_REPORT)


# ---- loader / 内容完整性 ----------------------------------------------------


def test_meta_and_dimensions(report: Report) -> None:
    assert report.slug == "chat-agent-evaluation"
    assert "Agent" in report.title and "评估" in report.title
    assert report.date == "2026-06-02"
    # 7 个评估维度,每个 worked example 字段齐全
    assert len(report.dimensions) == 7
    for d in report.dimensions:
        assert d.name and d.plain and d.setup and d.question and d.good and d.bad and d.scored
    names = " ".join(d.name for d in report.dimensions)
    # 覆盖四个角度 + RAG + 可靠性 + 克制
    assert "回答质量" in names and "任务完成" in names and "过程轨迹" in names
    assert "可靠性" in names and "克制" in names and "依据性" in names and "生产在线" in names


def test_eval_genre_uses_default_labels(report: Report) -> None:
    """评估体裁:不填 dimensions_meta,标签回退到默认(铺垫→问→好答→坏答→怎么判分)。"""
    assert report.dim_labels.section_title == ""
    assert report.dim_labels.setup == "铺垫"
    assert report.dim_labels.good == "好答"
    assert report.dim_labels.bad == "坏答"
    assert report.dim_labels.scored == "怎么判分"
    # 评估体裁不覆盖 benchmarks_title 也行;这份给了自定义标题
    assert report.benchmarks_title == "代表性方法 · 评测速览"


def test_sections_cover_judge_bias_and_terminal_state(report: Report) -> None:
    text = " ".join(s.heading + s.body + " ".join(s.bullets) for s in report.sections)
    # 两条暗线:裁判偏差 + 校验终态/连胜率
    assert "裁判" in text and "去偏" in text
    assert "终态" in text and ("连胜率" in text or "pass^k" in text)
    # RAG 专题
    assert "RAGAS" in text and "依据性" in text


def test_benchmarks_and_gaps(report: Report) -> None:
    bnames = " ".join(b.name for b in report.benchmarks)
    assert "G-Eval" in bnames and "MT-Bench" in bnames
    assert "τ-bench" in bnames and "agentevals" in bnames and "RAGAS" in bnames
    assert len(report.pitfalls) >= 5
    # 对照本项目:gaps 指向真实评估组件
    comps = " ".join(g.component for g in report.gaps)
    assert "chat" in comps and "轨迹" in comps and "裁判去偏" in comps


def test_sources_are_http_and_cover_key_papers(report: Report) -> None:
    assert report.sources
    assert all(s.url.startswith("http") for s in report.sources)
    urls = " ".join(s.url for s in report.sources)
    # G-Eval + τ-bench + RAGAS 三篇关键来源
    assert "arxiv.org/abs/2303.16634" in urls
    assert "arxiv.org/abs/2406.12045" in urls
    assert "arxiv.org/abs/2309.15217" in urls


# ---- 可读性守卫:正文不得含读者无法对应的字母数字代号 ------------------------

# 与既有报告同一套黑名单:Session 缩写 S<n>、内部 golden 编号、内部指标编号、
# 占位符「正确答案 X」—— 评估体裁同样不该出现。
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


def test_eval_lists_chat_agent_report(client: TestClient) -> None:
    body = client.get("/eval").text
    assert 'href="/eval/report/chat-agent-evaluation"' in body
    assert "对话 / 工具型 Agent" in body


def test_chat_agent_report_page_renders(client: TestClient) -> None:
    resp = client.get("/eval/report/chat-agent-evaluation")
    assert resp.status_code == 200
    body = resp.text
    # 内容关键点
    assert "G-Eval" in body and "τ-bench" in body and "RAGAS" in body
    assert "89.1%" in body or "0.514" in body
    # 评估体裁默认标签生效
    assert "铺垫" in body and "怎么判分" in body
    assert "好答" in body and "坏答" in body
    # 来源可点 + 返回链接
    assert "arxiv.org/abs/2406.12045" in body
    assert 'href="/eval"' in body
