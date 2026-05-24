"""LLM prefill prompt builder + constrained Pydantic schema。spec § 7.3。"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from dashboard.derive.deep_card_types import AlternativeItem, FieldProvenance


@dataclass(frozen=True)
class PrefillRequest:
    """单个 cap 的 prefill 上下文 — 装配 prompt 用。"""

    cap_id: str
    cap_name_cn: str
    linked_spec_paths: list[str]
    linked_memory_paths: list[str]
    decisions_summary: list[tuple[str, str]]  # [(decision_id, title), ...]


class PrefillResponse(BaseModel):
    """LLM 输出 schema — 全字段 + per-field provenance。"""

    model_config = ConfigDict(extra="forbid")
    what: str | None = None
    what_provenance: FieldProvenance | None = None
    why: str | None = None
    why_provenance: FieldProvenance | None = None
    alternatives: list[AlternativeItem] = Field(default_factory=list)
    alternatives_provenance: FieldProvenance | None = None
    chosen_alternative: str | None = None
    chosen_alternative_provenance: FieldProvenance | None = None
    tradeoff: str | None = None
    tradeoff_provenance: FieldProvenance | None = None
    lessons_learned: str | None = None
    lessons_learned_provenance: FieldProvenance | None = None


class SingleFieldPrefillResponse(BaseModel):
    """AI 草拟单字段 — 通过 backend/app/scripts/prefill_deep_cards CLI 批量调用。

    (原 POST /cap/{id}/ai_draft/{name} endpoint 已在 Plan 1 退役)
    """

    model_config = ConfigDict(extra="forbid")
    value: str
    provenance: FieldProvenance


SYSTEM_RULES = """\
你是金融研投助手项目的复习卡片助手。任务:基于给定的 spec/memory/decision 来源,
为某个 capability 生成 DeepCard 字段内容(中文,精炼)。

严格规则(违反将被拒绝入库):
1. 每个生成字段必须配 `*_provenance` 含 `quote`(≤30 字,从 source 原文截取)
   和 `source`(具体文件 path,允许 #section anchor)。
2. `quote` 必须是 source 文件中 substring 真实存在的文字(允许 markdown 标点差异)。
3. 如果某字段从 source 中找不到根据,请置该字段为 null + provenance 也为 null,
   不要凭空编造。
4. `what` <= 2 句话;`why` <= 200 字;`tradeoff` <= 200 字;
   `alternatives` 3-5 项 + brief_tradeoff <= 30 字;
   `chosen_alternative` 必须是 alternatives 列表中某 name 的精确字符串。
5. 输出 JSON 严格遵守提供的 schema。
"""


def _format_sources(req: PrefillRequest) -> str:
    lines: list[str] = []
    lines.append("**Linked specs (优先来源):**")
    for s in req.linked_spec_paths:
        lines.append(f"- {s}")
    lines.append("")
    if req.linked_memory_paths:
        lines.append("**Linked memory (经验/教训来源):**")
        for m in req.linked_memory_paths:
            lines.append(f"- {m}")
        lines.append("")
    if req.decisions_summary:
        lines.append("**已抽取决策卡 (linked decisions):**")
        for did, title in req.decisions_summary:
            lines.append(f"- [{did}] {title}")
        lines.append("")
    return "\n".join(lines)


def build_full_prefill_prompt(req: PrefillRequest) -> str:
    """全字段 prefill prompt — batch CLI 用。"""
    return (
        f"{SYSTEM_RULES}\n\n"
        f"# Capability\n\n"
        f"- id: `{req.cap_id}`\n"
        f"- 名称: {req.cap_name_cn}\n\n"
        f"# 来源材料\n\n"
        f"{_format_sources(req)}\n"
        f"# 任务\n\n"
        f"基于上述来源,生成 DeepCard 字段:what / why / alternatives / chosen_alternative / "
        f"tradeoff / lessons_learned,以及每个字段的 provenance(quote + source)。\n"
        f"对找不到根据的字段,**置 null 不要编造**。"
    )


_FIELD_HINTS: dict[str, str] = {
    "what": "做了什么(1-2 句事实陈述)",
    "why": "为什么这么选(动机 + 主要约束,<200 字)",
    "alternatives": "业界 alternatives 数组(3-5 项,每项 name + brief_tradeoff)",
    "chosen_alternative": "alternatives 中我们选的 name(必须精确匹配)",
    "tradeoff": "我们的最终取舍(<200 字)",
    "lessons_learned": "事后撞坑教训(从 memory feedback_*.md 抽)",
}


def build_single_field_prefill_prompt(req: PrefillRequest, *, field_name: str) -> str:
    """单字段 prefill prompt — V2 "AI 草拟" 按钮用。"""
    hint = _FIELD_HINTS.get(field_name, field_name)
    return (
        f"{SYSTEM_RULES}\n\n"
        f"# Capability\n\n"
        f"- id: `{req.cap_id}`\n"
        f"- 名称: {req.cap_name_cn}\n\n"
        f"# 来源材料\n\n"
        f"{_format_sources(req)}\n"
        f"# 任务\n\n"
        f"仅生成单字段 `{field_name}`({hint})及其 provenance。输出 schema:\n"
        f"`{{value: str, provenance: {{quote, source}}}}`。\n"
        f"找不到根据时,**置 value = ''** + provenance.quote = '' 表示放弃。"
    )
