"""上下文工程调研研报的 loader / 可读性 / 端点 / 体裁标签测试。

这份是「调研/综述」体裁(非「评估」体裁),用 report.py 的 dimensions_meta /
benchmarks_title 自定义区标题与行标签,与 chat-agent-loop-survey 同构。
归到「上下文与记忆」维度页(/m/context),不挂在评估页 /eval。纯净增文件,
不碰 main 既有测试。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from dashboard.derive.report import Report, load_report

REPORTS_DIR = Path(__file__).parent.parent.parent / "data" / "reports"
CE_REPORT = REPORTS_DIR / "context-engineering-survey.yaml"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    from dashboard import server

    monkeypatch.setattr(server, "DB_PATH", tmp_path / "board.db")
    return TestClient(server.app)


@pytest.fixture
def report() -> Report:
    return load_report(CE_REPORT)


# ---- loader / 内容完整性 ----------------------------------------------------


def test_meta_and_dimensions(report: Report) -> None:
    assert report.slug == "context-engineering-survey"
    assert "上下文工程" in report.title and "怎么做" in report.title
    assert report.date == "2026-06-04"
    # 7 个上下文工程设计决策,每个 worked example 字段齐全
    assert len(report.dimensions) == 7
    for d in report.dimensions:
        assert d.name and d.plain and d.setup and d.question and d.good and d.bad and d.scored
    names = " ".join(d.name for d in report.dimensions)
    # 覆盖窗口分区 / 大工具结果 / 压缩 / 协议红线 / 记忆注入 / token 计数 / 窗口外笔记
    assert "窗口分区" in names and "工具结果" in names and "压缩" in names
    assert "协议红线" in names and "记忆注入" in names and "token" in names and "窗口外笔记" in names


def test_survey_genre_labels(report: Report) -> None:
    """调研体裁:区标题与行标签被 dimensions_meta / benchmarks_title 覆盖。"""
    assert report.dim_labels.section_title == "7 个上下文工程设计决策 · 每个配一个真实场景"
    assert report.dim_labels.setup == "场景"
    assert report.dim_labels.good == "好做法"
    assert report.dim_labels.bad == "翻车点"
    # 评估体裁的默认词不应泄漏到这份报告的标签里
    assert report.dim_labels.scored != "怎么判分"
    assert report.benchmarks_title == "代表系统 / 方法 · 上下文管理机制速览"


def test_benchmarks_and_gaps(report: Report) -> None:
    bnames = " ".join(b.name for b in report.benchmarks)
    assert "Manus" in bnames and "Claude Code" in bnames and "MemGPT" in bnames
    assert "Zep" in bnames and "Anthropic" in bnames
    assert len(report.pitfalls) >= 8
    # 对照本项目:gaps 指向重设计草案与现状代码的真实组件
    comps = " ".join(g.component for g in report.gaps)
    assert "循环状态提示" in comps and "token 估算" in comps and "记忆注入" in comps
    # 业务样例落地:worked example 用本项目真实标的场景
    text = " ".join(f"{d.setup} {d.good} {d.bad}" for d in report.dimensions)
    assert "宁德时代" in text and "持仓" in text


def test_sources_are_http_and_cover_key_refs(report: Report) -> None:
    assert report.sources
    assert all(s.url.startswith("http") for s in report.sources)
    urls = " ".join(s.url for s in report.sources)
    # 关键一手来源:Anthropic 工程博客 + Manus 博客 + qwen 官方口径 + 退化实证论文
    assert "anthropic.com/engineering" in urls
    assert "manus.im/blog" in urls
    assert "qwen.readthedocs.io" in urls
    assert "arxiv.org/abs/2307.03172" in urls  # lost in the middle
    assert "arxiv.org/abs/2404.06654" in urls  # RULER


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


def test_context_dimension_page_lists_ce_report(client: TestClient) -> None:
    """调研体裁:上下文工程报告归到「上下文与记忆」维度页(/m/context),不在评估页 /eval。"""
    page = client.get("/m/context").text
    assert 'href="/eval/report/context-engineering-survey"' in page
    assert "上下文工程" in page
    assert "深度调研" in page
    # 评估页不应列这份调研报告(它不是评估方法论)
    eval_body = client.get("/eval").text
    assert "context-engineering-survey" not in eval_body


def test_ce_report_page_renders(client: TestClient) -> None:
    resp = client.get("/eval/report/context-engineering-survey")
    assert resp.status_code == 200
    body = resp.text
    # 内容关键点
    assert "KV-cache" in body and "Manus" in body and "MemGPT" in body
    assert "前缀" in body and "压缩" in body and "宁德时代" in body
    # 调研体裁标签已生效(自定义行标签 + 区标题),评估体裁默认词不应出现
    assert "场景" in body and "好做法" in body and "翻车点" in body
    assert "7 个上下文工程设计决策" in body
    assert "评估维度" not in body
    assert "怎么判分" not in body
    # 来源可点 + 返回链接
    assert "manus.im/blog" in body
    assert 'href="/eval"' in body
