"""对话流评估脚本 — yaml 加载 + 校验 + 类型化。

设计与 dashboard/derive/report.py 一脉相承:必填缺失即 fail loud,
全部冻结 dataclass。脚本是评估的数据 SSOT,本模块只读不写。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

VALID_TIERS = ("直球", "自然难", "对抗")
VALID_LENGTHS = ("短", "中", "长")
VALID_DIMENSIONS = (
    "知识更新",
    "单跳召回",
    "多跳推理",
    "时间推理",
    "克制弃答",
    "偏好一致",
    "持仓仲裁",
)


def _req(value: object, ctx: str) -> object:
    if value is None or value == "" or value == []:
        raise ValueError(f"script yaml 缺失必填字段: {ctx}")
    return value


@dataclass(frozen=True)
class Turn:
    role: str  # "u" 用户 / "a" 助手
    text: str


@dataclass(frozen=True)
class ScriptSession:
    n: int
    date: date
    length: str  # 短/中/长
    turns: tuple[Turn, ...]


@dataclass(frozen=True)
class DbCheck:
    """单条数据库断言描述。type 决定 params 里要什么键,由断言引擎解释。"""

    type: str
    params: dict[str, object]


@dataclass(frozen=True)
class DbAssertionGroup:
    after_session: int
    checks: tuple[DbCheck, ...]


@dataclass(frozen=True)
class Probe:
    tier: str
    dimension: str
    q: str
    expect_contain: tuple[str, ...]
    expect_not: tuple[str, ...]
    judge_rubric: str
    swap_order_invariant: bool = False
    answerable: bool = True  # False = 弃答题(正确行为是指出无法回答)


@dataclass(frozen=True)
class Script:
    script_id: str
    title: str
    family: str
    substrate: str
    sessions: tuple[ScriptSession, ...]
    db_assertions: tuple[DbAssertionGroup, ...]
    probes: tuple[Probe, ...]


def _parse_turns(raw: object, ctx: str) -> tuple[Turn, ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"script yaml: {ctx}.turns 必须是非空 list")
    out: list[Turn] = []
    for i, t in enumerate(raw):
        if not isinstance(t, dict) or len(t) != 1:
            raise ValueError(f"script yaml: {ctx}.turns[{i}] 必须是单键 mapping(u: / a:)")
        role, text = next(iter(t.items()))
        if role not in ("u", "a"):
            raise ValueError(f"script yaml: {ctx}.turns[{i}] 角色必须是 u 或 a,实得 {role}")
        out.append(Turn(role=str(role), text=str(_req(text, f"{ctx}.turns[{i}]"))))
    return tuple(out)


def _parse_sessions(raw: object) -> tuple[ScriptSession, ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("script yaml: sessions 必须是非空 list")
    out: list[ScriptSession] = []
    for i, s in enumerate(raw):
        ctx = f"sessions[{i}]"
        if not isinstance(s, dict):
            raise ValueError(f"script yaml: {ctx} 必须是 mapping")
        length = str(_req(s.get("length"), f"{ctx}.length"))
        if length not in VALID_LENGTHS:
            raise ValueError(f"script yaml: {ctx}.length 必须是 {VALID_LENGTHS},实得 {length}")
        d = s.get("date")
        if not isinstance(d, date):
            raise ValueError(f"script yaml: {ctx}.date 必须是 ISO 日期")
        n_raw = _req(s.get("n"), f"{ctx}.n")
        out.append(
            ScriptSession(
                n=int(n_raw),  # type: ignore[call-overload]
                date=d,
                length=length,
                turns=_parse_turns(s.get("turns"), ctx),
            )
        )
    return tuple(out)


def _parse_db_assertions(raw: object) -> tuple[DbAssertionGroup, ...]:
    if not raw:
        return ()
    if not isinstance(raw, list):
        raise ValueError("script yaml: db_assertions 必须是 list")
    out: list[DbAssertionGroup] = []
    for i, g in enumerate(raw):
        ctx = f"db_assertions[{i}]"
        if not isinstance(g, dict):
            raise ValueError(f"script yaml: {ctx} 必须是 mapping")
        checks_raw = g.get("assert")
        if not isinstance(checks_raw, list) or not checks_raw:
            raise ValueError(f"script yaml: {ctx}.assert 必须是非空 list")
        checks: list[DbCheck] = []
        for j, c in enumerate(checks_raw):
            if not isinstance(c, dict):
                raise ValueError(f"script yaml: {ctx}.assert[{j}] 必须是 mapping")
            ctype = str(_req(c.get("type"), f"{ctx}.assert[{j}].type"))
            params = {str(k): v for k, v in c.items() if k != "type"}
            checks.append(DbCheck(type=ctype, params=params))
        after_raw = _req(g.get("after"), f"{ctx}.after")
        out.append(
            DbAssertionGroup(
                after_session=int(after_raw),  # type: ignore[call-overload]
                checks=tuple(checks),
            )
        )
    return tuple(out)


def _parse_probes(raw: object) -> tuple[Probe, ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("script yaml: probes 必须是非空 list")
    out: list[Probe] = []
    for i, p in enumerate(raw):
        ctx = f"probes[{i}]"
        if not isinstance(p, dict):
            raise ValueError(f"script yaml: {ctx} 必须是 mapping")
        tier = str(_req(p.get("tier"), f"{ctx}.tier"))
        if tier not in VALID_TIERS:
            raise ValueError(f"script yaml: {ctx}.tier 必须是 {VALID_TIERS},实得 {tier}")
        dimension = str(_req(p.get("dimension"), f"{ctx}.dimension"))
        if dimension not in VALID_DIMENSIONS:
            raise ValueError(
                f"script yaml: {ctx}.dimension 必须是 {VALID_DIMENSIONS},实得 {dimension}"
            )
        out.append(
            Probe(
                tier=tier,
                dimension=dimension,
                q=str(_req(p.get("q"), f"{ctx}.q")),
                expect_contain=tuple(str(x) for x in (p.get("expect_contain") or [])),
                expect_not=tuple(str(x) for x in (p.get("expect_not") or [])),
                judge_rubric=str(_req(p.get("judge_rubric"), f"{ctx}.judge_rubric")),
                swap_order_invariant=bool(p.get("swap_order_invariant", False)),
                answerable=bool(p.get("answerable", True)),
            )
        )
    return tuple(out)


def load_script(path: Path) -> Script:
    """加载 + 校验脚本 yaml → 类型化 Script。非法即抛 ValueError 带上下文。"""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"script yaml 顶层必须是 mapping,实得 {type(data).__name__}")
    return Script(
        script_id=str(_req(data.get("script_id"), "script_id")),
        title=str(_req(data.get("title"), "title")),
        family=str(_req(data.get("family"), "family")),
        substrate=str(_req(data.get("substrate"), "substrate")),
        sessions=_parse_sessions(data.get("sessions")),
        db_assertions=_parse_db_assertions(data.get("db_assertions")),
        probes=_parse_probes(data.get("probes")),
    )
