"""派生层共享类型。"""

from __future__ import annotations

import hashlib
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


@dataclass(frozen=True)
class Decision:
    """决策(从 spec section 或 memory frontmatter 派生)。spec § 11.3。"""

    id: str  # sha256(version + layer + title)[:12]
    date: str  # ISO date(file mtime 或 frontmatter date)
    version: str  # "v0.8.5" / "M2" / "unversioned" / "unknown"
    layer: str  # "01" - "08" / "META"(spec § 3.1 keywords 反向归类后)
    title: str  # frontmatter name 或 spec ## § 标题
    why: str  # description 或 spec 段第一段
    refs: tuple[str, ...]  # 文件相对路径(frozen 用 tuple)
    state: str = "active"  # M3 默认 active,M3.x deprecated detect


def compute_decision_id(version: str, layer: str, title: str) -> str:
    """spec § 7.4:sha256(version + layer + title)[:12]。"""
    payload = f"{version}|{layer}|{title}".encode()
    return hashlib.sha256(payload).hexdigest()[:12]
