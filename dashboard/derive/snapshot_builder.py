"""聚合派生层输出到一个 Snapshot,可序列化到 sqlite payload。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from .capability_resolver import load_capabilities, resolve_all
from .path_router import load_dimensions
from .types import Capability, CapabilityStatus, SnapshotDict


@dataclass(frozen=True)
class LayerSummary:
    id: str
    number: str
    name_cn: str
    name_en: str
    lit: int
    wip: int
    todo: int
    total: int
    capabilities: list[Capability]


@dataclass(frozen=True)
class Snapshot:
    """单次派生快照,JSON 序列化进 derived_snapshot.payload。"""

    refreshed_at: str
    layers: list[LayerSummary]
    total_lit: int
    total_wip: int
    total_todo: int
    total: int

    def to_dict(self) -> SnapshotDict:
        return cast(
            SnapshotDict,
            {
                "refreshed_at": self.refreshed_at,
                "layers": [
                    {**asdict(layer), "capabilities": [asdict(c) for c in layer.capabilities]}
                    for layer in self.layers
                ],
                "total_lit": self.total_lit,
                "total_wip": self.total_wip,
                "total_todo": self.total_todo,
                "total": self.total,
            },
        )


def build_snapshot(
    project_root: Path,
    config_dir: Path,
    overrides: dict[str, CapabilityStatus] | None = None,
    refreshed_at: str | None = None,
) -> Snapshot:
    """读 yaml + 派生 + 聚合到 Snapshot。"""
    refreshed_at = refreshed_at or datetime.now(UTC).isoformat()
    main_dims, _catch_all = load_dimensions(config_dir / "dimensions.yaml")
    caps = load_capabilities(config_dir / "capabilities.yaml")
    resolved = resolve_all(caps, project_root, overrides)
    by_dim: dict[str, list[Capability]] = {d.id: [] for d in main_dims}
    for c in resolved:
        by_dim.setdefault(c.dimension, []).append(c)
    layers: list[LayerSummary] = []
    for d in main_dims:
        items = by_dim.get(d.id, [])
        layers.append(
            LayerSummary(
                id=d.id,
                number=d.number,
                name_cn=d.name_cn,
                name_en=d.name_en,
                lit=sum(1 for c in items if c.status == "lit"),
                wip=sum(1 for c in items if c.status == "wip"),
                todo=sum(1 for c in items if c.status == "todo"),
                total=len(items),
                capabilities=items,
            )
        )
    return Snapshot(
        refreshed_at=refreshed_at,
        layers=layers,
        total_lit=sum(layer.lit for layer in layers),
        total_wip=sum(layer.wip for layer in layers),
        total_todo=sum(layer.todo for layer in layers),
        total=sum(layer.total for layer in layers),
    )
