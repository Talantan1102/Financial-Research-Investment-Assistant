"""长期记忆故障模式研报的 loader / 可读性 / 端点测试。

《跨会话记忆 · 怎么评估》的姊妹篇:评估体裁但 worked-example 区是故障模式
(用 dimensions_meta.title 自定义区标题,行标签保持评估体裁默认)。
沉淀自记忆评估体系重建的两轮 workflow 调研。纯净增文件,不碰既有测试。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from dashboard.derive.report import Report, load_report

REPORTS_DIR = Path(__file__).parent.parent.parent / "data" / "reports"
FAILURE_MODES_REPORT = REPORTS_DIR / "memory-failure-modes.yaml"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    from dashboard import server

    monkeypatch.setattr(server, "DB_PATH", tmp_path / "board.db")
    return TestClient(server.app)


@pytest.fixture
def report() -> Report:
    return load_report(FAILURE_MODES_REPORT)


# ---- loader / 内容完整性 ----------------------------------------------------


def test_meta_and_dimensions(report: Report) -> None:
    assert report.slug == "memory-failure-modes"
    assert "故障模式" in report.title
    assert report.date == "2026-06-04"
    # 9 个代表性故障模式,每个 worked example 字段齐全
    assert len(report.dimensions) == 9
    for d in report.dimensions:
        assert d.name and d.plain and d.setup and d.question and d.good and d.bad and d.scored
    names = " ".join(d.name for d in report.dimensions)
    # 四个能力维度 + 本项目独有的持仓仲裁都有代表
    assert "知识更新" in names and "偏好一致" in names
    assert "时间推理" in names and "弃答" in names and "持仓仲裁" in names


def test_custom_section_title_keeps_eval_labels(report: Report) -> None:
    """worked-example 区标题自定义为故障模式,行标签保持评估体裁默认。"""
    assert report.dim_labels.section_title == "9 个代表性故障模式 · 每个配一个完整造题示例"
    assert report.dim_labels.setup == "铺垫"
    assert report.dim_labels.good == "好答"
    assert report.dim_labels.bad == "坏答"
    assert report.dim_labels.scored == "怎么判分"
    assert report.benchmarks_title == "证据来源速览 · 谁踩过这些坑"


def test_sections_cover_four_dims_and_invariance(report: Report) -> None:
    headings = " ".join(s.heading for s in report.sections)
    assert "知识更新" in headings and "偏好一致" in headings
    assert "时间推理" in headings and "弃答" in headings
    assert "持仓仲裁" in headings and "不变量开关" in headings
    text = " ".join(s.heading + s.body + " ".join(s.bullets) for s in report.sections)
    # 关键量化锚点在正文里
    assert "6%" in text  # 多跳冲突全员崩塌
    assert "97.8%" in text  # Mem0 垃圾记忆事故
    assert "15%" in text  # 裁判对知行不一的敏感度
    assert "66.1%" in text  # 信息不足上下文幻觉率


def test_benchmarks_pitfalls_gaps(report: Report) -> None:
    bnames = " ".join(b.name for b in report.benchmarks)
    assert "LongMemEval" in bnames and "Mem0" in bnames
    assert "PrefEval" in bnames and "AbstentionBench" in bnames
    assert len(report.pitfalls) >= 5
    # 对照本项目:gaps 指向五个脚本族 + runner
    comps = " ".join(g.component for g in report.gaps)
    assert "观点演化族" in comps and "偏好画像族" in comps
    assert "弃答陷阱族" in comps and "持仓仲裁族" in comps and "runner" in comps


def test_sources_are_http_and_cover_key_papers(report: Report) -> None:
    assert report.sources
    assert all(s.url.startswith("http") for s in report.sources)
    urls = " ".join(s.url for s in report.sources)
    # 三个维度各至少一篇关键来源 + 生产事故 issue
    assert "arxiv.org/abs/2502.09597" in urls  # PrefEval
    assert "arxiv.org/abs/2406.09170" in urls  # Test of Time
    assert "arxiv.org/abs/2506.09038" in urls  # AbstentionBench
    assert "github.com/mem0ai/mem0/issues" in urls


# ---- 可读性守卫:正文不得含读者无法对应的字母数字代号 ------------------------

# 与既有报告同一套黑名单,本报告曾因 spec 用 D1/L1 代号被用户打回,在此锁死。
_OPAQUE = [
    re.compile(r"(?<![A-Za-z])S\d"),
    re.compile(r"c5-golden"),
    re.compile(r"Metric\s*\d"),
    re.compile(r"正确答案\s*X"),
    re.compile(r"(?<![A-Za-z0-9])[BD]\d{1,2}(?![A-Za-z0-9%])"),  # B1/D7 类自创决策代号
    re.compile(r"(?<![A-Za-z0-9])L[123](?![A-Za-z0-9])"),  # L1/L2/L3 难度代号
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


def test_eval_lists_failure_modes_report(client: TestClient) -> None:
    body = client.get("/eval").text
    assert 'href="/eval/report/memory-failure-modes"' in body
    assert "故障模式与造题" in body


def test_failure_modes_report_page_renders(client: TestClient) -> None:
    resp = client.get("/eval/report/memory-failure-modes")
    assert resp.status_code == 200
    body = resp.text
    # 内容关键点:四维度代表模式 + 量化锚点 + 独有维度
    assert "间接指代推翻" in body and "知行不一" in body
    assert "时间窗过滤" in body and "信息不足碎片" in body
    assert "持仓陈述不入账" in body
    assert "97.8%" in body and "66.1%" in body
    # 自定义区标题生效,评估体裁默认行标签保留
    assert "9 个代表性故障模式" in body
    assert "铺垫" in body and "怎么判分" in body
    # 来源可点 + 返回链接
    assert "arxiv.org/abs/2506.09038" in body
    assert 'href="/eval"' in body
