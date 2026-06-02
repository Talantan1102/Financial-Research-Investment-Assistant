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


@dataclass(frozen=True)
class EvalLayer:
    """一个评估层级 = 矩阵的一列。"""

    id: str  # component / agent / system / regression
    name_cn: str
    name_en: str
    desc: str


@dataclass(frozen=True)
class EvalCell:
    """单元格 = 某子系统在某层级的覆盖情况。"""

    subsystem_id: str
    layer_id: str
    status: EvalStatus
    methods: tuple[str, ...]
    evidence: tuple[str, ...]  # 代码路径
    gap: str  # 缺口说明;covered 时通常为空串


@dataclass(frozen=True)
class EvalSubsystem:
    """一个子系统 = 矩阵的一行,含 4 个 cell(key = layer id)。"""

    id: str
    name_cn: str
    name_en: str
    summary: str
    cells: dict[str, EvalCell] = field(default_factory=dict)


@dataclass(frozen=True)
class EvalMatrix:
    """整张矩阵 = layers(列) + subsystems(行)。"""

    layers: tuple[EvalLayer, ...]
    subsystems: tuple[EvalSubsystem, ...]


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

    return EvalCell(
        subsystem_id=subsystem_id,
        layer_id=layer_id,
        status=status,  # 已校验在 _VALID_STATUS 内,运行时即 EvalStatus
        methods=tuple(str(m) for m in methods_raw),
        evidence=tuple(str(e) for e in evidence_raw),
        gap=str(raw.get("gap") or ""),
    )


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

    return EvalMatrix(layers=layers, subsystems=tuple(subsystems))


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
