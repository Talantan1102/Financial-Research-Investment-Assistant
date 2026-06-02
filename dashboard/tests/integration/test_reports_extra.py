"""KB 检索 + 跨会话记忆两份研报的 loader/可读性/端点测试。

main 的 test_report.py 只覆盖 deep-research-report-eval;这两份是本分支净增,
单独建文件测(纯加法,不碰 main 的测试文件)。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from dashboard.derive.report import Report, load_report

REPORTS_DIR = Path(__file__).parent.parent.parent / "data" / "reports"
KB_REPORT = REPORTS_DIR / "knowledge-base-retrieval-eval.yaml"
MEMORY_REPORT = REPORTS_DIR / "cross-session-memory-eval.yaml"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    from dashboard import server

    monkeypatch.setattr(server, "DB_PATH", tmp_path / "board.db")
    return TestClient(server.app)


@pytest.fixture
def kb_report() -> Report:
    return load_report(KB_REPORT)


@pytest.fixture
def memory_report() -> Report:
    return load_report(MEMORY_REPORT)


# ---- loader / 内容完整性 ----------------------------------------------------


def test_kb_report_meta_and_dimensions(kb_report: Report) -> None:
    assert kb_report.slug == "knowledge-base-retrieval-eval"
    assert "知识库检索" in kb_report.title
    assert kb_report.date == "2026-06-02"
    assert len(kb_report.dimensions) == 9
    for d in kb_report.dimensions:
        assert d.name and d.plain and d.setup and d.question and d.good and d.bad and d.scored
    names = " ".join(d.name for d in kb_report.dimensions)
    assert "召回@k" in names and "nDCG" in names and "chunking" in names


def test_kb_report_benchmarks_gaps_sources(kb_report: Report) -> None:
    bnames = " ".join(b.name for b in kb_report.benchmarks)
    assert "BEIR" in bnames and "MTEB" in bnames and "RAGAS" in bnames
    assert len(kb_report.pitfalls) >= 5
    assert any("qrels" in g.component or "qrels" in g.suggestion for g in kb_report.gaps)
    assert all(s.url.startswith("http") for s in kb_report.sources)
    assert any("arxiv.org/abs/2104.08663" in s.url for s in kb_report.sources)


def test_memory_report_meta_and_dimensions(memory_report: Report) -> None:
    assert memory_report.slug == "cross-session-memory-eval"
    assert len(memory_report.dimensions) == 6
    names = " ".join(d.name for d in memory_report.dimensions)
    assert "知识更新" in names and "弃答" in names
    assert any("arxiv.org/abs/2410.10813" in s.url for s in memory_report.sources)


# ---- 可读性守卫:报告正文不得含读者无法对应的字母数字代号 --------------------

# Session 缩写 S4/S9、内部 golden 编号 c5-golden-XXX、内部指标编号 Metric N、
# 占位符「正确答案 X」—— 这些读者无从解码,审查时已清掉,在此锁死防回流。
_OPAQUE = [
    re.compile(r"(?<![A-Za-z])S\d"),  # S4 / S20 等 Session 缩写
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
    for g in r.gaps:
        parts.append(g.component + g.current + g.suggestion)
    return "\n".join(parts)


@pytest.mark.parametrize("path", [KB_REPORT, MEMORY_REPORT])
def test_reports_have_no_opaque_codes(path: Path) -> None:
    text = _report_text(load_report(path))
    for pat in _OPAQUE:
        m = pat.search(text)
        assert m is None, f"{path.name} 含读者无法对应的代号: {m.group(0)!r}"


# ---- 端点:报告页渲染 + /eval 列表 ------------------------------------------


def test_eval_lists_both_new_reports(client: TestClient) -> None:
    body = client.get("/eval").text
    assert "深度报告" in body
    assert 'href="/eval/report/knowledge-base-retrieval-eval"' in body
    assert 'href="/eval/report/cross-session-memory-eval"' in body


def test_kb_report_page_renders(client: TestClient) -> None:
    resp = client.get("/eval/report/knowledge-base-retrieval-eval")
    assert resp.status_code == 200
    body = resp.text
    assert "知识库检索" in body
    assert "铺垫" in body and "怎么判分" in body
    assert "好答" in body and "坏答" in body
    assert "nDCG" in body and "BEIR" in body
    assert 'href="/eval"' in body
    assert "arxiv.org/abs/2104.08663" in body


def test_memory_report_page_renders(client: TestClient) -> None:
    resp = client.get("/eval/report/cross-session-memory-eval")
    assert resp.status_code == 200
    body = resp.text
    assert "跨会话记忆" in body
    assert "知识更新" in body and "LongMemEval" in body
    # 可读性:Session 改写后页面不应再出现裸 S20/S4
    assert "第20次对话" in body or "第4次对话" in body
