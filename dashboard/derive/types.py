"""派生层共享类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

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
    id: DimensionId
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
