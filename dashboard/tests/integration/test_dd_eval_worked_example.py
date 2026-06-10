"""深度研报评估报告「本项目实跑实例」增补的守护测试。

2026-06-10 在 deep-research-report-eval 报告里增补三节图文实例(茅台回测全流程 /
四把尺子算分 / 消融对照),配两张 svg 图。本文件只测增补内容(loader 完整性 +
图例存在 + 端点内联 + 可读性守卫),不动 main 的 test_report.py。纯净增文件。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from dashboard.derive.report import Report, load_report

REPORTS_DIR = Path(__file__).parent.parent.parent / "data" / "reports"
FIGURES_DIR = Path(__file__).parent.parent.parent / "templates" / "figures"
DD_REPORT = REPORTS_DIR / "deep-research-report-eval.yaml"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    from dashboard import server

    monkeypatch.setattr(server, "DB_PATH", tmp_path / "board.db")
    return TestClient(server.app)


@pytest.fixture
def report() -> Report:
    return load_report(DD_REPORT)


# ---- loader / 增补内容完整性 -------------------------------------------------


def test_worked_example_sections_present(report: Report) -> None:
    """三节实跑实例齐全:全流程 / 四把尺子 / 消融对照,各带要点。"""
    headings = [s.heading for s in report.sections]
    assert any("把时钟拨回 2024-06-30" in h for h in headings)
    assert any("四把尺子" in h and "茅台" in h for h in headings)
    assert any("消融对照" in h for h in headings)
    for s in report.sections:
        if "时钟拨回" in s.heading or "四把尺子" in s.heading or "消融" in s.heading:
            assert s.body, f"实例节缺正文: {s.heading}"
            assert len(s.bullets) >= 4, f"实例节要点不足: {s.heading}"


def test_figures_declared_and_files_exist(report: Report) -> None:
    """两张实跑图:声明、文件存在、带 caption。"""
    figures = {s.figure: s for s in report.sections if s.figure}
    assert "dd-eval-backtest-flow.svg" in figures
    assert "dd-eval-four-rulers.svg" in figures
    for name, sec in figures.items():
        svg = FIGURES_DIR / name
        assert svg.is_file(), f"图例文件缺失: {name}"
        assert "<svg" in svg.read_text(encoding="utf-8")
        assert sec.figure_caption, f"图例缺 caption: {name}"


def test_worked_example_grounded_in_real_pipeline(report: Report) -> None:
    """实例内容锚定真实实现:题库构成 / 评委模型 / 容差 / 无泄漏副线 / 落库。"""
    blob = "\n".join(
        s.heading + s.body + s.figure_caption + " ".join(s.bullets) for s in report.sections
    )
    assert "40 道" in blob and "8 家公司" in blob and "5 个评估时点" in blob
    assert "600519.SH" in blob and "2024-06-30" in blob
    assert "deepseek-v4-flash" in blob and "qwen-plus" in blob and "qwen-max" in blob
    assert "±1%" in blob  # 数值核对容差
    assert "2026-04-30" in blob  # 无泄漏副线口径
    assert "git 版本号" in blob and "消融变体" in blob  # 落库字段白话名
    # 去推荐化后口径:四把尺子,且讲清预测回测为何下线
    assert "四把尺子" in blob
    assert "去推荐化" in blob


# ---- 可读性守卫:增补正文不得用内部代号 --------------------------------------

_OPAQUE = [
    re.compile(r"\bM[1-5]\b"),  # metric 内部代号
    re.compile(r"\bV[0-3]\b"),  # 消融变体内部代号(要用白话:基线/拔掉知识库…)
    re.compile(r"(?<![A-Za-z])T2\.\d"),  # plan task 编号
]


def test_worked_example_has_no_opaque_codes(report: Report) -> None:
    text = "\n".join(
        s.heading + s.body + s.figure_caption + " ".join(s.bullets) for s in report.sections
    )
    for pat in _OPAQUE:
        m = pat.search(text)
        assert m is None, f"实例正文含读者无法对应的代号: {m.group(0)!r}"


def test_figures_use_plain_names_no_codes(report: Report) -> None:
    """svg 图内文案同样不用内部代号(读者直接看图)。"""
    for name in ("dd-eval-backtest-flow.svg", "dd-eval-four-rulers.svg"):
        svg = (FIGURES_DIR / name).read_text(encoding="utf-8")
        texts = "".join(re.findall(r">([^<>]+)</text>", svg))
        for pat in _OPAQUE:
            m = pat.search(texts)
            assert m is None, f"{name} 图内含内部代号: {m.group(0)!r}"


# ---- 端点:报告页内联渲染两张图 ----------------------------------------------


def test_report_page_renders_worked_example_with_figures(client: TestClient) -> None:
    resp = client.get("/eval/report/deep-research-report-eval")
    assert resp.status_code == 200
    body = resp.text
    # 三节实例在页面上
    assert "把时钟拨回 2024-06-30" in body
    assert "消融对照" in body
    # 两张 svg 真实内联(各自命名空间 class 前缀在场,非 <img> 引用)
    assert body.count('class="report-figure"') == 2
    assert "ddbf-" in body, "全流程图 svg 未内联"
    assert "ddfr-" in body, "四把尺子图 svg 未内联"
    assert body.count('class="report-figcaption"') == 2
    # 实例细节渲染
    assert "600519.SH" in body and "deepseek-v4-flash" in body
