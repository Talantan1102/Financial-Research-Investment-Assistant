"""元评估研报的 loader / 可读性 / 端点测试。

《长期记忆 · 故障模式与造题》的下一环:那篇讲题怎么造,这篇讲怎么论证
评估体系本身可信(效度/信度/区分度/运营健康四类准则)。
沉淀自评估体系重建过程中的元评估 workflow 调研。纯净增文件。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from dashboard.derive.report import Report, load_report

REPORTS_DIR = Path(__file__).parent.parent.parent / "data" / "reports"
META_EVAL_REPORT = REPORTS_DIR / "eval-meta-evaluation.yaml"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    from dashboard import server

    monkeypatch.setattr(server, "DB_PATH", tmp_path / "board.db")
    return TestClient(server.app)


@pytest.fixture
def report() -> Report:
    return load_report(META_EVAL_REPORT)


# ---- loader / 内容完整性 ----------------------------------------------------


def test_meta_and_dimensions(report: Report) -> None:
    assert report.slug == "eval-meta-evaluation"
    assert "元评估" in report.title
    assert report.date == "2026-06-05"
    assert len(report.dimensions) == 9
    for d in report.dimensions:
        assert d.name and d.plain and d.setup and d.question and d.good and d.bad and d.scored
    names = " ".join(d.name for d in report.dimensions)
    # 四类准则的代表都在场
    assert "效标效度" in names and "误差棒" in names
    assert "聚类标准误" in names and "裁判" in names
    assert "区分度" in names and "重测信度" in names and "一键复现" in names


def test_sections_cover_four_categories_and_gap_map(report: Report) -> None:
    headings = " ".join(s.heading for s in report.sections)
    assert "效度" in headings and "信度" in headings
    assert "区分度" in headings and "运营健康" in headings
    assert "对照本项目" in headings
    text = " ".join(s.heading + s.body + " ".join(s.bullets) for s in report.sections)
    # 关键量化锚点
    assert "50.9%" in text  # 裁判判客观对错仅略好于随机
    assert "87.4%" in text  # Arena-Hard 区分度
    assert "97%" in text  # LongMemEval 裁判一致率
    assert "3 倍" in text  # 聚类标准误低估


def test_benchmarks_pitfalls_gaps(report: Report) -> None:
    bnames = " ".join(b.name for b in report.benchmarks)
    assert "Arena-Hard" in bnames and "JudgeBench" in bnames
    assert "BetterBench" in bnames and "LongMemEval" in bnames
    assert len(report.pitfalls) >= 5
    comps = " ".join(g.component for g in report.gaps)
    assert "效度" in comps and "信度" in comps
    assert "区分度" in comps and "裁判审计" in comps


def test_sources_are_http_and_cover_key_papers(report: Report) -> None:
    assert report.sources
    assert all(s.url.startswith("http") for s in report.sources)
    urls = " ".join(s.url for s in report.sources)
    assert "arxiv.org/abs/2411.00640" in urls  # Adding Error Bars
    assert "arxiv.org/abs/2410.12784" in urls  # JudgeBench
    assert "arxiv.org/abs/2411.12990" in urls  # BetterBench
    assert "anthropic.com/engineering/demystifying-evals-for-ai-agents" in urls


# ---- 可读性守卫:与既有报告同一套黑名单 + 决策/难度代号 ----------------------

_OPAQUE = [
    re.compile(r"(?<![A-Za-z])S\d"),
    re.compile(r"c5-golden"),
    re.compile(r"Metric\s*\d"),
    re.compile(r"正确答案\s*X"),
    re.compile(r"(?<![A-Za-z0-9])[BD]\d{1,2}(?![A-Za-z0-9%])"),
    re.compile(r"(?<![A-Za-z0-9])L[123](?![A-Za-z0-9])"),
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


def test_eval_lists_meta_eval_report(client: TestClient) -> None:
    body = client.get("/eval").text
    assert 'href="/eval/report/eval-meta-evaluation"' in body
    assert "元评估" in body


def test_meta_eval_report_page_renders(client: TestClient) -> None:
    resp = client.get("/eval/report/eval-meta-evaluation")
    assert resp.status_code == 200
    body = resp.text
    assert "效标效度" in body and "聚类标准误" in body
    assert "位置翻转" in body and "一键复现" in body
    assert "50.9%" in body and "87.4%" in body
    assert "9 个元评估准则" in body
    assert "铺垫" in body and "怎么判分" in body
    assert "arxiv.org/abs/2410.12784" in body
    assert 'href="/eval"' in body
