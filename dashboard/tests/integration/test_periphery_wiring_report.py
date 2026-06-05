"""周边接线调研研报的 loader / 可读性 / 端点 / 体裁标签测试。

这份是「调研/综述」体裁(非「评估」体裁),用 report.py 的 dimensions_meta /
benchmarks_title 自定义区标题与行标签,与 subagent-dispatch-survey 同构。
归到「工具接口与协议」维度页(/m/tool,与 subagent-dispatch-survey 同页共存),
不挂在评估页 /eval。纯净增文件,不碰 main 既有测试。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from dashboard.derive.report import Report, load_report

REPORTS_DIR = Path(__file__).parent.parent.parent / "data" / "reports"
PW_REPORT = REPORTS_DIR / "periphery-wiring-survey.yaml"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    from dashboard import server

    monkeypatch.setattr(server, "DB_PATH", tmp_path / "board.db")
    return TestClient(server.app)


@pytest.fixture
def report() -> Report:
    return load_report(PW_REPORT)


# ---- loader / 内容完整性 ----------------------------------------------------


def test_meta_and_dimensions(report: Report) -> None:
    assert report.slug == "periphery-wiring-survey"
    assert "周边接线" in report.title and "怎么做" in report.title
    assert report.date == "2026-06-04"
    # 7 个接线设计决策,每个 worked example 字段齐全
    assert len(report.dimensions) == 7
    for d in report.dimensions:
        assert d.name and d.plain and d.setup and d.question and d.good and d.bad and d.scored
    names = " ".join(d.name for d in report.dimensions)
    # 覆盖控制权判据 / 数量治理 / 信号工具 / 记忆双轨 / 渐进披露 / 生命周期 / 脚本
    assert "控制权" in names and "数量" in names and "信号工具" in names
    assert "记忆" in names and "渐进披露" in names and "生命周期" in names and "脚本" in names


def test_survey_genre_labels(report: Report) -> None:
    """调研体裁:区标题与行标签被 dimensions_meta / benchmarks_title 覆盖。"""
    assert report.dim_labels.section_title == "7 个接线设计决策 · 每个配一个真实场景"
    assert report.dim_labels.setup == "场景"
    assert report.dim_labels.good == "好做法"
    assert report.dim_labels.bad == "翻车点"
    # 评估体裁的默认词不应泄漏到这份报告的标签里
    assert report.dim_labels.scored != "怎么判分"
    assert report.benchmarks_title == "代表系统 / 方法 · 周边接线机制速览"


def test_benchmarks_and_gaps(report: Report) -> None:
    bnames = " ".join(b.name for b in report.benchmarks)
    assert "MCP" in bnames and "Claude Code" in bnames and "OpenAI" in bnames
    assert "Voyager" in bnames and "Agent Skills" in bnames
    assert len(report.pitfalls) >= 8
    # 对照本项目:gaps 指向重设计草案的真实裁决
    comps = " ".join(g.component for g in report.gaps)
    assert "工具清单" in comps and "升级提议" in comps and "技能" in comps
    # 业务样例落地:worked example 用本项目真实标的场景
    text = " ".join(f"{d.setup} {d.good} {d.bad}" for d in report.dimensions)
    assert "宁德时代" in text and "持仓" in text and "风险" in text


def test_sources_are_http_and_cover_key_refs(report: Report) -> None:
    assert report.sources
    assert all(s.url.startswith("http") for s in report.sources)
    urls = " ".join(s.url for s in report.sources)
    # 关键一手来源:MCP 规范 + Anthropic 工程博客 + OpenAI handoff + qwen 官方红线 + 实证论文
    assert "modelcontextprotocol.io" in urls
    assert "anthropic.com/engineering" in urls
    assert "openai.github.io/openai-agents-python/handoffs" in urls
    assert "alibabacloud.com" in urls
    assert "arxiv.org/abs/2505.10570" in urls  # LongFuncEval
    assert "arxiv.org/abs/2305.16291" in urls  # Voyager


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


def test_tool_dimension_page_lists_both_reports(client: TestClient) -> None:
    """调研体裁:周边接线报告归到「工具接口与协议」维度页(/m/tool),与子 agent 派发研报共存。"""
    page = client.get("/m/tool").text
    assert 'href="/eval/report/periphery-wiring-survey"' in page
    assert "周边接线" in page
    # 既有的子 agent 派发研报仍在同页
    assert 'href="/eval/report/subagent-dispatch-survey"' in page
    # 评估页不应列这份调研报告(它不是评估方法论)
    eval_body = client.get("/eval").text
    assert "periphery-wiring-survey" not in eval_body


def test_pw_report_page_renders(client: TestClient) -> None:
    resp = client.get("/eval/report/periphery-wiring-survey")
    assert resp.status_code == 200
    body = resp.text
    # 内容关键点
    assert "MCP" in body and "万物皆工具" in body and "宁德时代" in body
    assert "信号工具" in body and "渐进披露" in body
    # 调研体裁标签已生效(自定义行标签 + 区标题),评估体裁默认词不应出现
    assert "场景" in body and "好做法" in body and "翻车点" in body
    assert "7 个接线设计决策" in body
    assert "评估维度" not in body
    assert "怎么判分" not in body
    # 来源可点 + 返回链接
    assert "modelcontextprotocol.io" in body
    assert 'href="/eval"' in body
