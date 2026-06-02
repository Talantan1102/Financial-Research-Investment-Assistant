"""评估体系覆盖矩阵 — yaml 加载 + 校验 + 类型化 + 汇总统计。

子系统(行) × 评估层级(列)的覆盖矩阵。数据 SSOT 在
``dashboard/config/eval_system.yaml``,本模块只读不写。

设计:
- status 取值只允许 covered / partial / gap;任何非法值在加载期 fail loud
  (抛 ValueError 带 context),不静默降级 — 评估矩阵自己也得"被评估"。
- 每个 subsystem 必须为 4 个 layer 各提供一个 cell;cell 缺失同样 fail loud。
- ``matrix_summary`` 给页面 summary 条用:总数 / 三态计数 / 覆盖率(整数百分比)
  + 每列 covered 数(用于"哪一层最弱"的横向对照)。

论文锚点: Li et al., Agent Harness Engineering: A Survey (2026),
          §8 Verification & Evaluation。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

EvalStatus = Literal["covered", "partial", "gap"]

_VALID_STATUS: frozenset[str] = frozenset({"covered", "partial", "gap"})

# 评估方法 family — 决定详情卡片的配色分组。六类覆盖全部方法 tag。
FAMILY_LABELS: dict[str, str] = {
    "deterministic": "确定性离线",
    "mock": "替身隔离",
    "judge": "LLM 评判",
    "replay": "录放回放",
    "e2e": "端到端",
    "regression": "回归鲁棒",
}
_VALID_FAMILY: frozenset[str] = frozenset(FAMILY_LABELS)


@dataclass(frozen=True)
class EvalLayer:
    """一个评估层级 = 矩阵的一列。"""

    id: str  # component / agent / system / regression
    name_cn: str
    name_en: str
    desc: str


@dataclass(frozen=True)
class EvalTodo:
    """一条待办 = 补该格缺口的计划项(task + 工期估计 + 是否已完成)。"""

    task: str
    est: str  # 工期估计,如 "~0.5d";可空串
    done: bool  # 已完成则前端打勾 + 划线


@dataclass(frozen=True)
class EvalMethodSample:
    """一条方法样例 = 喂什么 / 期望什么 / 怎么判对错。"""

    given: str
    expect: str
    verdict: str


@dataclass(frozen=True)
class EvalMethodCase:
    """多类 case 方法里的一类 = 标签 + 一行白话样例。"""

    label: str
    sample: str


@dataclass(frozen=True)
class EvalMethod:
    """方法词典里的一条 = 把晦涩的方法 tag 翻成白话 + 配真实样例。

    数据来自 eval_system.yaml 顶层 ``method_glossary``。详情面板渲染时按
    cell.methods 逐个解析成 ``EvalMethod`` 卡片。
    """

    id: str
    name_cn: str
    name_en: str
    family: str  # FAMILY_LABELS 之一
    how: str  # 白话解释怎么评
    sample: EvalMethodSample
    cases: tuple[EvalMethodCase, ...] = ()  # 多类 case 才有,否则空

    @property
    def family_label(self) -> str:
        return FAMILY_LABELS.get(self.family, self.family)


@dataclass(frozen=True)
class EvalCell:
    """单元格 = 某子系统在某层级的覆盖情况。"""

    subsystem_id: str
    layer_id: str
    status: EvalStatus
    methods: tuple[str, ...]
    evidence: tuple[str, ...]  # 代码路径
    gap: str  # 缺口说明;covered 时通常为空串
    todo: tuple[EvalTodo, ...] = ()  # 补缺口的计划;无则空


@dataclass(frozen=True)
class EvalSubsystem:
    """一个子系统 = 矩阵的一行,含 4 个 cell(key = layer id)。"""

    id: str
    name_cn: str
    name_en: str
    summary: str
    cells: dict[str, EvalCell] = field(default_factory=dict)


@dataclass(frozen=True)
class EvalLearningStep:
    """学习路径的一步 = 标题 + 类型(看/动手) + 工期 + 白话说明 + 关联到哪些矩阵格。"""

    title: str
    kind: str  # 看 / 动手 / 动手+读 / 持续
    est: str  # 工期估计,可空串
    what: str  # 白话说明这一步做什么
    maps: tuple[str, ...] = ()  # 关联的子系统·层级,如 "对话 Agent·组件级"


@dataclass(frozen=True)
class EvalMatrix:
    """整张矩阵 = layers(列) + subsystems(行) + 方法词典 + 组件级评估学习路径。"""

    layers: tuple[EvalLayer, ...]
    subsystems: tuple[EvalSubsystem, ...]
    glossary: dict[str, EvalMethod] = field(default_factory=dict)
    learning_path: tuple[EvalLearningStep, ...] = ()

    def resolve_methods(self, cell: EvalCell) -> tuple[EvalMethod, ...]:
        """把一个 cell 的 method tag 列表解析成词典里的 ``EvalMethod`` 卡片。

        加载期已校验每个引用的 method 都在词典内,故此处不会 KeyError。
        """
        return tuple(self.glossary[m] for m in cell.methods)


@dataclass(frozen=True)
class MatrixSummary:
    """页面 summary 条 + legend 用的聚合统计。"""

    total: int
    covered: int
    partial: int
    gap: int
    coverage_pct: int  # covered / total * 100,取整
    covered_by_layer: dict[str, int]  # layer_id -> 该列 covered 的 cell 数


def _require(value: object, ctx: str) -> object:
    """缺失即 fail loud。"""
    if value is None:
        raise ValueError(f"eval_system.yaml 缺失必填字段: {ctx}")
    return value


def _parse_cell(
    raw: object,
    *,
    subsystem_id: str,
    layer_id: str,
) -> EvalCell:
    """解析单格;status 非法 / 缺失即抛 ValueError 带 context。"""
    ctx = f"subsystem '{subsystem_id}' · layer '{layer_id}'"
    if not isinstance(raw, dict):
        raise ValueError(
            f"eval_system.yaml: {ctx} 的 cell 必须是 mapping,实得 {type(raw).__name__}"
        )

    status = raw.get("status")
    if status is None:
        raise ValueError(f"eval_system.yaml: {ctx} 缺失 status")
    if status not in _VALID_STATUS:
        raise ValueError(
            f"eval_system.yaml: {ctx} 的 status 非法: {status!r} (只允许 {sorted(_VALID_STATUS)})"
        )

    methods_raw = raw.get("methods") or []
    evidence_raw = raw.get("evidence") or []
    if not isinstance(methods_raw, list):
        raise ValueError(f"eval_system.yaml: {ctx} 的 methods 必须是 list")
    if not isinstance(evidence_raw, list):
        raise ValueError(f"eval_system.yaml: {ctx} 的 evidence 必须是 list")

    todo_raw = raw.get("todo") or []
    if not isinstance(todo_raw, list):
        raise ValueError(f"eval_system.yaml: {ctx} 的 todo 必须是 list")
    todo: list[EvalTodo] = []
    for i, item in enumerate(todo_raw):
        if not isinstance(item, dict):
            raise ValueError(f"eval_system.yaml: {ctx} 的 todo[{i}] 必须是 mapping")
        task = item.get("task")
        if not task:
            raise ValueError(f"eval_system.yaml: {ctx} 的 todo[{i}] 缺失 task")
        todo.append(
            EvalTodo(task=str(task), est=str(item.get("est") or ""), done=bool(item.get("done")))
        )

    return EvalCell(
        subsystem_id=subsystem_id,
        layer_id=layer_id,
        status=status,  # 已校验在 _VALID_STATUS 内,运行时即 EvalStatus
        methods=tuple(str(m) for m in methods_raw),
        evidence=tuple(str(e) for e in evidence_raw),
        gap=str(raw.get("gap") or ""),
        todo=tuple(todo),
    )


def _parse_glossary(raw: object) -> dict[str, EvalMethod]:
    """解析顶层 method_glossary → {method_id: EvalMethod};字段缺失/family 非法即 fail loud。"""
    if not isinstance(raw, dict):
        raise ValueError(
            f"eval_system.yaml: method_glossary 必须是 mapping,实得 {type(raw).__name__}"
        )

    glossary: dict[str, EvalMethod] = {}
    for mid, entry in raw.items():
        ctx = f"method_glossary['{mid}']"
        if not isinstance(entry, dict):
            raise ValueError(f"eval_system.yaml: {ctx} 必须是 mapping")

        family = entry.get("family")
        if family not in _VALID_FAMILY:
            raise ValueError(
                f"eval_system.yaml: {ctx} 的 family 非法: {family!r} (只允许 {sorted(_VALID_FAMILY)})"
            )

        sample_raw = entry.get("sample")
        if not isinstance(sample_raw, dict):
            raise ValueError(f"eval_system.yaml: {ctx} 缺失 sample mapping")
        sample = EvalMethodSample(
            given=str(_require(sample_raw.get("given"), f"{ctx}.sample.given")),
            expect=str(_require(sample_raw.get("expect"), f"{ctx}.sample.expect")),
            verdict=str(_require(sample_raw.get("verdict"), f"{ctx}.sample.verdict")),
        )

        cases_raw = entry.get("cases") or []
        if not isinstance(cases_raw, list):
            raise ValueError(f"eval_system.yaml: {ctx} 的 cases 必须是 list")
        cases = tuple(
            EvalMethodCase(
                label=str(_require(c.get("label"), f"{ctx}.cases[{i}].label")),
                sample=str(_require(c.get("sample"), f"{ctx}.cases[{i}].sample")),
            )
            for i, c in enumerate(cases_raw)
            if isinstance(c, dict)
            or _raise(f"eval_system.yaml: {ctx}.cases[{i}] 必须是 mapping")
        )

        glossary[str(mid)] = EvalMethod(
            id=str(mid),
            name_cn=str(_require(entry.get("name_cn"), f"{ctx}.name_cn")),
            name_en=str(_require(entry.get("name_en"), f"{ctx}.name_en")),
            family=str(family),
            how=str(_require(entry.get("how"), f"{ctx}.how")),
            sample=sample,
            cases=cases,
        )
    return glossary


def _parse_learning_path(raw: object) -> tuple[EvalLearningStep, ...]:
    """解析顶层 learning_path → EvalLearningStep 元组;title/what 缺失即 fail loud。"""
    if not isinstance(raw, list):
        raise ValueError(
            f"eval_system.yaml: learning_path 必须是 list,实得 {type(raw).__name__}"
        )
    steps: list[EvalLearningStep] = []
    for i, item in enumerate(raw):
        ctx = f"learning_path[{i}]"
        if not isinstance(item, dict):
            raise ValueError(f"eval_system.yaml: {ctx} 必须是 mapping")
        maps_raw = item.get("maps") or []
        if not isinstance(maps_raw, list):
            raise ValueError(f"eval_system.yaml: {ctx} 的 maps 必须是 list")
        steps.append(
            EvalLearningStep(
                title=str(_require(item.get("title"), f"{ctx}.title")),
                kind=str(item.get("kind") or ""),
                est=str(item.get("est") or ""),
                what=str(_require(item.get("what"), f"{ctx}.what")),
                maps=tuple(str(m) for m in maps_raw),
            )
        )
    return tuple(steps)


def _raise(msg: str) -> bool:
    raise ValueError(msg)


def load_eval_matrix(path: Path) -> EvalMatrix:
    """加载 + 校验 eval_system.yaml → 类型化 ``EvalMatrix``。

    Raises:
        ValueError: yaml 结构非法 / status 取值非法 / cell 缺失。
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"eval_system.yaml 顶层必须是 mapping,实得 {type(data).__name__}")

    layers_raw = _require(data.get("layers"), "layers")
    subsystems_raw = _require(data.get("subsystems"), "subsystems")
    if not isinstance(layers_raw, list) or not layers_raw:
        raise ValueError("eval_system.yaml: layers 必须是非空 list")
    if not isinstance(subsystems_raw, list) or not subsystems_raw:
        raise ValueError("eval_system.yaml: subsystems 必须是非空 list")

    layers = tuple(
        EvalLayer(
            id=str(_require(d.get("id"), "layer.id")),
            name_cn=str(_require(d.get("name_cn"), f"layer '{d.get('id')}' name_cn")),
            name_en=str(_require(d.get("name_en"), f"layer '{d.get('id')}' name_en")),
            desc=str(_require(d.get("desc"), f"layer '{d.get('id')}' desc")),
        )
        for d in layers_raw
    )
    layer_ids = [layer.id for layer in layers]

    subsystems: list[EvalSubsystem] = []
    for sd in subsystems_raw:
        sub_id = str(_require(sd.get("id"), "subsystem.id"))
        cells_raw = sd.get("cells")
        if not isinstance(cells_raw, dict):
            raise ValueError(f"eval_system.yaml: subsystem '{sub_id}' 缺失 cells mapping")

        cells: dict[str, EvalCell] = {}
        for layer_id in layer_ids:
            if layer_id not in cells_raw:
                raise ValueError(
                    f"eval_system.yaml: subsystem '{sub_id}' 缺失 layer '{layer_id}' 的 cell"
                )
            cells[layer_id] = _parse_cell(
                cells_raw[layer_id], subsystem_id=sub_id, layer_id=layer_id
            )

        subsystems.append(
            EvalSubsystem(
                id=sub_id,
                name_cn=str(_require(sd.get("name_cn"), f"subsystem '{sub_id}' name_cn")),
                name_en=str(_require(sd.get("name_en"), f"subsystem '{sub_id}' name_en")),
                summary=str(sd.get("summary") or ""),
                cells=cells,
            )
        )

    # 方法词典(可选 top-level);若提供则校验每个被引用的 method 都有词条 — 否则 fail loud。
    # "评估矩阵自己也得被评估":cell 里写了方法 tag,词典就必须能解释它。
    glossary = _parse_glossary(data["method_glossary"]) if data.get("method_glossary") else {}
    if glossary:
        referenced = {m for sub in subsystems for cell in sub.cells.values() for m in cell.methods}
        missing = sorted(referenced - glossary.keys())
        if missing:
            raise ValueError(
                f"eval_system.yaml: 这些 cell 引用的评估方法在 method_glossary 中没有词条: {missing}"
            )

    # 组件级评估学习路径(可选 top-level)— 跨子系统的有序学习旅程,不属于单个 cell。
    learning_path = (
        _parse_learning_path(data["learning_path"]) if data.get("learning_path") else ()
    )

    return EvalMatrix(
        layers=layers,
        subsystems=tuple(subsystems),
        glossary=glossary,
        learning_path=learning_path,
    )


def matrix_summary(m: EvalMatrix) -> MatrixSummary:
    """汇总:总格数 / covered / partial / gap + 覆盖率 + 每列 covered 数。"""
    covered = partial = gap = 0
    covered_by_layer: dict[str, int] = {layer.id: 0 for layer in m.layers}

    for sub in m.subsystems:
        for layer_id, cell in sub.cells.items():
            if cell.status == "covered":
                covered += 1
                covered_by_layer[layer_id] = covered_by_layer.get(layer_id, 0) + 1
            elif cell.status == "partial":
                partial += 1
            else:  # gap
                gap += 1

    total = covered + partial + gap
    coverage_pct = round(covered / total * 100) if total else 0

    return MatrixSummary(
        total=total,
        covered=covered,
        partial=partial,
        gap=gap,
        coverage_pct=coverage_pct,
        covered_by_layer=covered_by_layer,
    )
