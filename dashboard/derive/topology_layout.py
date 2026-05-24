"""Plan 3 Task 1 — 首页 Topology SVG 7 模块坐标 + 进度计算。

论文 §2.3 关系语义:G/O 顶横切 · TCL 中段三件套 · V 旁路 · E 底盘。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModuleBox:
    dim_id: str
    letter: str
    name_cn: str
    paper_section: str
    x: int
    y: int
    width: int
    height: int


MODULES: tuple[ModuleBox, ...] = (
    ModuleBox("governance", "G", "治理", "§ 9", 20, 14, 220, 44),
    ModuleBox("observability", "O", "可观测", "§ 7", 260, 14, 220, 44),
    ModuleBox("tool", "T", "工具", "§ 4", 20, 90, 140, 100),
    ModuleBox("context", "C", "上下文", "§ 5", 180, 90, 140, 100),
    ModuleBox("lifecycle", "L", "生命周期", "§ 6", 340, 90, 140, 100),
    ModuleBox("execution", "E", "执行环境", "§ 3", 20, 232, 380, 48),
    ModuleBox("verification", "V", "验证", "§ 8", 420, 232, 80, 48),
)


@dataclass(frozen=True)
class ConnLine:
    from_id: str
    to_id: str
    type: str  # cross_cut | runtime | bypass


CONNECTIONS: tuple[ConnLine, ...] = (
    ConnLine("governance", "tool", "cross_cut"),
    ConnLine("governance", "context", "cross_cut"),
    ConnLine("governance", "lifecycle", "cross_cut"),
    ConnLine("observability", "tool", "cross_cut"),
    ConnLine("observability", "context", "cross_cut"),
    ConnLine("observability", "lifecycle", "cross_cut"),
    ConnLine("tool", "execution", "runtime"),
    ConnLine("context", "execution", "runtime"),
    ConnLine("lifecycle", "execution", "runtime"),
    ConnLine("verification", "lifecycle", "bypass"),
)


@dataclass(frozen=True)
class ModuleProgress:
    dim_id: str
    letter: str
    name_cn: str
    paper_section: str
    x: int
    y: int
    width: int
    height: int
    lit: int
    wip: int
    todo: int
    total: int

    @property
    def pct(self) -> int:
        return int((self.lit / self.total) * 100) if self.total else 0


def layout_with_progress(snap_layers: Sequence[Any]) -> list[ModuleProgress]:
    """合并 MODULES 几何 + snapshot 进度。"""
    by_id = {L["id"]: L for L in snap_layers}
    out: list[ModuleProgress] = []
    for m in MODULES:
        L = by_id.get(m.dim_id)
        if L is None:
            out.append(
                ModuleProgress(
                    dim_id=m.dim_id,
                    letter=m.letter,
                    name_cn=m.name_cn,
                    paper_section=m.paper_section,
                    x=m.x,
                    y=m.y,
                    width=m.width,
                    height=m.height,
                    lit=0,
                    wip=0,
                    todo=0,
                    total=0,
                )
            )
            continue
        out.append(
            ModuleProgress(
                dim_id=m.dim_id,
                letter=m.letter,
                name_cn=m.name_cn,
                paper_section=m.paper_section,
                x=m.x,
                y=m.y,
                width=m.width,
                height=m.height,
                lit=int(L.get("lit", 0)),
                wip=int(L.get("wip", 0)),
                todo=int(L.get("todo", 0)),
                total=int(L.get("total", 0)),
            )
        )
    return out


def connection_endpoints(
    modules_by_id: dict[str, ModuleProgress],
) -> list[tuple[ConnLine, tuple[int, int], tuple[int, int]]]:
    """计算每条连线的起止点(box edge 中点)。"""
    out = []
    for c in CONNECTIONS:
        a = modules_by_id.get(c.from_id)
        b = modules_by_id.get(c.to_id)
        if a is None or b is None:
            continue
        if a.y + a.height <= b.y:
            ax, ay = a.x + a.width // 2, a.y + a.height
            bx, by = b.x + b.width // 2, b.y
        elif b.y + b.height <= a.y:
            ax, ay = a.x + a.width // 2, a.y
            bx, by = b.x + b.width // 2, b.y + b.height
        else:
            if a.x < b.x:
                ax, ay = a.x + a.width, a.y + a.height // 2
                bx, by = b.x, b.y + b.height // 2
            else:
                ax, ay = a.x, a.y + a.height // 2
                bx, by = b.x + b.width, b.y + b.height // 2
        out.append((c, (ax, ay), (bx, by)))
    return out
