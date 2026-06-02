"""研究报告 — yaml 加载 + 校验 + 类型化。

研发看板里的长文研究报告(如"深度研报怎么评估")。数据 SSOT 在
``dashboard/data/reports/<slug>.yaml``,本模块只读不写。

设计与 eval_matrix 一脉相承:
- 必填字段缺失即 fail loud(抛 ValueError 带 context),不静默降级。
- 全部冻结 dataclass,渲染层零逻辑。

报告结构:meta + summary + 若干叙事 section + 能力维度(每个配 worked example)
+ benchmark 速览 + 坑 + 对照本项目缺口 + 来源。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


def _req(value: object, ctx: str) -> object:
    if value is None or value == "":
        raise ValueError(f"report yaml 缺失必填字段: {ctx}")
    return value


@dataclass(frozen=True)
class ReportSection:
    """一段叙事:标题 + 正文 + 可选要点列表。"""

    heading: str
    body: str
    bullets: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReportDimension:
    """一个能力维度,配完整 worked example(铺垫→问→好答→坏答→怎么判分)。"""

    name: str
    plain: str
    setup: str
    question: str
    good: str
    bad: str
    scored: str


@dataclass(frozen=True)
class ReportBenchmark:
    name: str
    what: str
    fit: str


@dataclass(frozen=True)
class ReportGap:
    """对照本项目:某块现状 + 可补什么。"""

    component: str
    current: str
    suggestion: str


@dataclass(frozen=True)
class ReportSource:
    title: str
    url: str


@dataclass(frozen=True)
class Report:
    slug: str
    title: str
    subtitle: str
    date: str
    basis: str  # 报告依据(来源数 / 方法)
    summary: str
    sections: tuple[ReportSection, ...]
    dimensions: tuple[ReportDimension, ...]
    benchmarks: tuple[ReportBenchmark, ...]
    pitfalls: tuple[str, ...]
    gaps: tuple[ReportGap, ...]
    sources: tuple[ReportSource, ...]


def _parse_sections(raw: object) -> tuple[ReportSection, ...]:
    if not raw:
        return ()
    if not isinstance(raw, list):
        raise ValueError("report yaml: sections 必须是 list")
    out: list[ReportSection] = []
    for i, s in enumerate(raw):
        if not isinstance(s, dict):
            raise ValueError(f"report yaml: sections[{i}] 必须是 mapping")
        bullets_raw = s.get("bullets") or []
        if not isinstance(bullets_raw, list):
            raise ValueError(f"report yaml: sections[{i}].bullets 必须是 list")
        out.append(
            ReportSection(
                heading=str(_req(s.get("heading"), f"sections[{i}].heading")),
                body=str(s.get("body") or ""),
                bullets=tuple(str(b) for b in bullets_raw),
            )
        )
    return tuple(out)


def _parse_dimensions(raw: object) -> tuple[ReportDimension, ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("report yaml: dimensions 必须是非空 list")
    out: list[ReportDimension] = []
    for i, d in enumerate(raw):
        if not isinstance(d, dict):
            raise ValueError(f"report yaml: dimensions[{i}] 必须是 mapping")
        ctx = f"dimensions[{i}]"
        out.append(
            ReportDimension(
                name=str(_req(d.get("name"), f"{ctx}.name")),
                plain=str(_req(d.get("plain"), f"{ctx}.plain")),
                setup=str(_req(d.get("setup"), f"{ctx}.setup")),
                question=str(_req(d.get("question"), f"{ctx}.question")),
                good=str(_req(d.get("good"), f"{ctx}.good")),
                bad=str(_req(d.get("bad"), f"{ctx}.bad")),
                scored=str(_req(d.get("scored"), f"{ctx}.scored")),
            )
        )
    return tuple(out)


def _parse_benchmarks(raw: object) -> tuple[ReportBenchmark, ...]:
    if not raw:
        return ()
    if not isinstance(raw, list):
        raise ValueError("report yaml: benchmarks 必须是 list")
    return tuple(
        ReportBenchmark(
            name=str(_req(b.get("name"), f"benchmarks[{i}].name")),
            what=str(_req(b.get("what"), f"benchmarks[{i}].what")),
            fit=str(_req(b.get("fit"), f"benchmarks[{i}].fit")),
        )
        for i, b in enumerate(raw)
        if isinstance(b, dict)
    )


def _parse_gaps(raw: object) -> tuple[ReportGap, ...]:
    if not raw:
        return ()
    if not isinstance(raw, list):
        raise ValueError("report yaml: gaps 必须是 list")
    return tuple(
        ReportGap(
            component=str(_req(g.get("component"), f"gaps[{i}].component")),
            current=str(_req(g.get("current"), f"gaps[{i}].current")),
            suggestion=str(_req(g.get("suggestion"), f"gaps[{i}].suggestion")),
        )
        for i, g in enumerate(raw)
        if isinstance(g, dict)
    )


def _parse_sources(raw: object) -> tuple[ReportSource, ...]:
    if not raw:
        return ()
    if not isinstance(raw, list):
        raise ValueError("report yaml: sources 必须是 list")
    return tuple(
        ReportSource(
            title=str(_req(s.get("title"), f"sources[{i}].title")),
            url=str(_req(s.get("url"), f"sources[{i}].url")),
        )
        for i, s in enumerate(raw)
        if isinstance(s, dict)
    )


def load_report(path: Path) -> Report:
    """加载 + 校验报告 yaml → 类型化 ``Report``。

    Raises:
        ValueError: 结构非法 / 必填字段缺失。
        FileNotFoundError: 报告文件不存在。
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"report yaml 顶层必须是 mapping,实得 {type(data).__name__}")

    meta = data.get("meta") or {}
    if not isinstance(meta, dict):
        raise ValueError("report yaml: meta 必须是 mapping")

    return Report(
        slug=str(_req(data.get("slug"), "slug")),
        title=str(_req(data.get("title"), "title")),
        subtitle=str(data.get("subtitle") or ""),
        date=str(meta.get("date") or ""),
        basis=str(meta.get("basis") or ""),
        summary=str(_req(data.get("summary"), "summary")),
        sections=_parse_sections(data.get("sections")),
        dimensions=_parse_dimensions(data.get("dimensions")),
        benchmarks=_parse_benchmarks(data.get("benchmarks")),
        pitfalls=tuple(str(p) for p in (data.get("pitfalls") or [])),
        gaps=_parse_gaps(data.get("gaps")),
        sources=_parse_sources(data.get("sources")),
    )
