"""计算类验证集 case schema + jsonl 读写(反向出题机 MVP)。

风格参照 ``eval.chatloop.scenario`` —— fail-loud(``_fail`` 统一 raise ValueError)/
``//`` 注释行与空行跳过 / case_id 查重 / 空集报错 / 逐行非法 json fail-loud。

一条 ``ComputationCase`` 描述「某窗口下对某些股票算某指标」的题目 + 标准答案(gold),
gold 的形状由 ``gold_shape`` 标记,判分器据此选数值/结构口径:
    scalar       → gold 是单个浮点数
    multi_scalar → gold 是 {label: float}
    ranking      → gold 是 [[name, val], ...](有序)
    set          → gold 是 [name, ...](无序集合)

jsonl 行格式(``//`` 注释行跳过),每行一个 ``dataclasses.asdict`` 序列化的对象:
    {"case_id": "comp-001", "intent": "区间收益", "difficulty": "简单",
     "question": "茅台过去一年涨了多少?", "stocks": ["600519.SH"],
     "indicator": "interval_return", "window": "2025-06-17~2026-06-17",
     "gold": 1.23, "gold_shape": "scalar",
     "tolerance": {"rel": 0.01}, "meta": {}}
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn

VALID_DIFFICULTY: tuple[str, ...] = ("简单", "中等", "复杂")
VALID_GOLD_SHAPE: tuple[str, ...] = ("scalar", "multi_scalar", "ranking", "set")

_REQUIRED_KEYS: tuple[str, ...] = (
    "case_id",
    "intent",
    "difficulty",
    "question",
    "stocks",
    "indicator",
    "window",
    "gold",
    "gold_shape",
    "tolerance",
)


@dataclass(frozen=True)
class ComputationCase:
    """单条计算类验证 case。``gold`` 形状由 ``gold_shape`` 标记(见模块 docstring)。"""

    case_id: str
    intent: str
    difficulty: str  # 简单 / 中等 / 复杂
    question: str
    stocks: list[str]
    indicator: str
    window: str
    gold: Any  # scalar=float; multi_scalar={label:float}; ranking=[[name,val],...]; set=[name,...]
    gold_shape: str  # scalar / multi_scalar / ranking / set
    tolerance: dict[str, Any]
    meta: dict[str, Any] = field(default_factory=dict)


def _fail(msg: str) -> NoReturn:
    raise ValueError(f"question_gen case 校验失败: {msg}")


def _validate(raw: dict[str, Any], seen: set[str]) -> ComputationCase:
    for key in _REQUIRED_KEYS:
        if key not in raw:
            _fail(f"缺失必填字段 {key!r}: {raw!r}")

    case_id = raw["case_id"]
    if not isinstance(case_id, str) or not case_id.strip():
        _fail(f"case_id 须为非空字符串: {raw!r}")
    if case_id in seen:
        _fail(f"case_id 重复: {case_id!r}")

    if not isinstance(raw["intent"], str) or not raw["intent"].strip():
        _fail(f"{case_id}: intent 须为非空字符串")
    if raw["difficulty"] not in VALID_DIFFICULTY:
        _fail(f"{case_id}: difficulty {raw['difficulty']!r} 不在枚举 {VALID_DIFFICULTY!r}")
    if not isinstance(raw["question"], str) or not raw["question"].strip():
        _fail(f"{case_id}: question 须为非空字符串")
    if not isinstance(raw["stocks"], list):
        _fail(f"{case_id}: stocks 须为列表")
    if not isinstance(raw["indicator"], str) or not raw["indicator"].strip():
        _fail(f"{case_id}: indicator 须为非空字符串")
    if not isinstance(raw["window"], str) or not raw["window"].strip():
        _fail(f"{case_id}: window 须为非空字符串")
    if raw["gold_shape"] not in VALID_GOLD_SHAPE:
        _fail(f"{case_id}: gold_shape {raw['gold_shape']!r} 不在枚举 {VALID_GOLD_SHAPE!r}")
    if not isinstance(raw["tolerance"], dict):
        _fail(f"{case_id}: tolerance 须为对象")

    meta = raw.get("meta")
    if meta is not None and not isinstance(meta, dict):
        _fail(f"{case_id}: meta 须为对象或省略")

    seen.add(case_id)
    return ComputationCase(
        case_id=case_id,
        intent=raw["intent"],
        difficulty=raw["difficulty"],
        question=raw["question"],
        stocks=list(raw["stocks"]),
        indicator=raw["indicator"],
        window=raw["window"],
        gold=raw["gold"],
        gold_shape=raw["gold_shape"],
        tolerance=dict(raw["tolerance"]),
        meta=dict(meta or {}),
    )


def dump_jsonl(cases: list[ComputationCase], path: Path) -> None:
    """每行一个 json(``dataclasses.asdict``)写出。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(dataclasses.asdict(c), ensure_ascii=False) for c in cases]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def load_jsonl(path: Path) -> list[ComputationCase]:
    """读 jsonl(``//`` 注释 + 空行跳过),逐行 fail-loud。空集 / 文件不存在报错。"""
    if not path.exists():
        _fail(f"case 文件不存在: {path}")
    out: list[ComputationCase] = []
    seen: set[str] = set()
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as e:
            _fail(f"第 {lineno} 行不是合法 JSON: {e}")
        if not isinstance(raw, dict):
            _fail(f"第 {lineno} 行须为对象")
        out.append(_validate(raw, seen))
    if not out:
        _fail(f"case 文件无有效 case: {path}")
    return out


__all__ = [
    "ComputationCase",
    "dump_jsonl",
    "load_jsonl",
    "VALID_DIFFICULTY",
    "VALID_GOLD_SHAPE",
]
