"""DeepCard / Flashcard / Provenance 类型。spec § 4.1。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PrefillSource = Literal["llm", "manual", "hybrid"]
TemplateKind = Literal["alternatives", "tradeoff", "lessons"]


class AlternativeItem(BaseModel):
    """alternatives 数组单项。"""

    model_config = ConfigDict(extra="forbid")
    name: str
    brief_tradeoff: str


class CodeAnchor(BaseModel):
    """关键代码入口。"""

    model_config = ConfigDict(extra="forbid")
    file: str
    line: int
    note: str = ""


class FieldProvenance(BaseModel):
    """单字段 provenance — quote + source。spec § 7.3。"""

    model_config = ConfigDict(extra="forbid")
    quote: str = Field(..., max_length=200)  # 30 字硬限太严,留 200 兜底
    source: str  # file path + optional #section


class SrsState(BaseModel):
    """SM-2 状态。"""

    model_config = ConfigDict(extra="forbid")
    confidence: int = Field(default=0, ge=0, le=5)
    ef: float = Field(default=2.5, ge=1.3)  # ease factor
    interval: int = 0  # days
    repetition: int = 0
    last_reviewed_at: datetime | None = None
    next_review_at: datetime | None = None


class DeepCard(BaseModel):
    """每个 capability 的深读卡。spec § 4.1。"""

    model_config = ConfigDict(extra="forbid")
    cap_id: str
    # 内容核心
    what: str | None = None
    why: str | None = None
    alternatives: list[AlternativeItem] = Field(default_factory=list)
    chosen_alternative: str | None = None
    tradeoff: str | None = None
    lessons_learned: str | None = None
    metrics: dict[str, str | float | int] = Field(default_factory=dict)
    # 链接图
    code_anchors: list[CodeAnchor] = Field(default_factory=list)
    linked_decisions: list[str] = Field(default_factory=list)
    linked_specs: list[str] = Field(default_factory=list)
    linked_memories: list[str] = Field(default_factory=list)
    linked_capabilities: list[str] = Field(default_factory=list)
    # SRS
    srs_state: SrsState = Field(default_factory=SrsState)
    # 防幻觉
    provenance: dict[str, FieldProvenance] = Field(default_factory=dict)
    # 元
    prefill_source: PrefillSource = "manual"
    prefill_at: datetime | None = None
    last_edited_at: datetime | None = None


class Flashcard(BaseModel):
    """从 DeepCard 派生的闪卡。spec § 5.5。"""

    model_config = ConfigDict(extra="forbid")
    id: str  # f"{cap_id}::{template_kind}"
    cap_id: str
    template_kind: TemplateKind
    question: str
    answer: str
    srs_state: SrsState = Field(default_factory=SrsState)
    created_at: datetime | None = None
    last_reviewed_at: datetime | None = None
