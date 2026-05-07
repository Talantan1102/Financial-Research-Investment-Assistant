"""派生层共享类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

DimensionId = Literal[
    "prompt_context",
    "tools_function",
    "orchestration",
    "memory",
    "rag_knowledge",
    "guardrails",
    "eval_observability",
    "cost_routing",
    "app_shell",
    "unknown",
]

CapabilityStatus = Literal["lit", "wip", "todo"]


@dataclass(frozen=True)
class DimensionConfig:
    id: str  # 主 8 维取 DimensionId 值;App Shell 6 项取子 id (frontend/backend/...)
    number: str  # "01"-"08" or "09"
    name_cn: str
    name_en: str
    paths: tuple[str, ...]
    keywords: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CapabilityConfig:
    id: str  # e.g. "01.multi_tier_signature"
    dimension: DimensionId
    name_cn: str
    name_en: str
    derive_rule: dict[str, Any]  # 5 类 rule type, see capability_resolver


@dataclass(frozen=True)
class Capability:
    id: str
    dimension: DimensionId
    name_cn: str
    name_en: str
    status: CapabilityStatus
    derived_status: CapabilityStatus  # 派生原值,与 status 比较可知是否 override


class CapabilityDict(TypedDict):
    id: str
    dimension: DimensionId
    name_cn: str
    name_en: str
    status: CapabilityStatus
    derived_status: CapabilityStatus


class LayerSummaryDict(TypedDict):
    id: DimensionId
    number: str
    name_cn: str
    name_en: str
    lit: int
    wip: int
    todo: int
    total: int
    capabilities: list[CapabilityDict]


class SnapshotDict(TypedDict):
    refreshed_at: str
    layers: list[LayerSummaryDict]
    total_lit: int
    total_wip: int
    total_todo: int
    total: int


@dataclass(frozen=True)
class AppShellItem:
    """App Shell 第 9 行单项 — 显示文件计数。"""

    id: str  # "frontend" / "backend" / "auth" / "database" / "connectors" / "infra"
    name_cn: str
    file_count: int
