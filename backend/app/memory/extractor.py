"""LLM extractor for chat memory write pipeline (spec § 4 Step 2).

Path A (agent-triggered) 也可走 LLMExtractor 但 agent 已给半结构化, 实际多数情况
跳过 LLM call (Plan 4 archival_memory_insert MCP tool 直接传 content + reasoning).
本 plan 主要用于 Path B (Plan 2B) end-of-session batch + Path A fallback (agent
没明确给 entities/edges 时).

Plan 2A 仅实现 `extract` (Path A 单 episode); Plan 2B 加 `extract_facts` (跨轮 5 turn 滑动窗口).
契约 ref: docs/superpowers/plans/2026-05-11-c5-plan-shared-contracts.md § 17 A2 (4)
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.memory.registry import REL_TYPES

_logger = logging.getLogger(__name__)


# ===== importance 三档常量 (spec § 11 算法补丁 #3) =====

IMPORTANCE_HIGH: float = 0.9
IMPORTANCE_MEDIUM: float = 0.5
IMPORTANCE_LOW: float = 0.2
IMPORTANCE_TIERS: set[float] = {IMPORTANCE_HIGH, IMPORTANCE_MEDIUM, IMPORTANCE_LOW}


# ===== Pydantic schemas (强 validation, LLM JSON output 必须满足) =====


class ExtractedEntity(BaseModel):
    """spec § 4 Step 2 输出 schema 之 entities 元素."""

    entity_type: str
    entity_label: str
    properties: dict[str, Any] = Field(default_factory=dict)

    @field_validator("entity_type")
    @classmethod
    def _validate_entity_type(cls, v: str) -> str:
        from app.memory.registry import ENTITY_TYPES

        if v not in ENTITY_TYPES:
            raise ValueError(f"entity_type {v!r} not in whitelist {ENTITY_TYPES}")
        return v


class ExtractedEdge(BaseModel):
    """spec § 4 Step 2 输出 schema 之 edges 元素."""

    rel_type: str
    source_label: str
    target_label: str
    valid_from: str  # ISO 8601 with timezone
    valid_to: str | None = None
    importance: float
    reasoning: str
    properties: dict[str, Any] = Field(default_factory=dict)

    @field_validator("rel_type")
    @classmethod
    def _validate_rel_type(cls, v: str) -> str:
        if v not in REL_TYPES:
            raise ValueError(f"rel_type {v!r} not in whitelist {REL_TYPES}")
        return v

    @field_validator("importance")
    @classmethod
    def _validate_importance_three_tier(cls, v: float) -> float:
        # 算法深度补丁 #3: importance 三档严守
        if v not in IMPORTANCE_TIERS:
            raise ValueError(
                f"importance {v} must be one of {sorted(IMPORTANCE_TIERS)} "
                f"(0.9=high / 0.5=medium / 0.2=low)"
            )
        return v


class ExtractionOutput(BaseModel):
    entities: list[ExtractedEntity]
    edges: list[ExtractedEdge]


# ===== Extraction prompt (spec § 4 Step 2 模板) =====

_EXTRACTION_SYSTEM_PROMPT = """\
你帮金融 chat agent 从对话中抽"用户事实", 存入 graph memory.

# Ontology (你只能用这些类型)
Entity types: User / Stock / Industry / Sector / Metric / Strategy / Concept
Relationship types: HOLDS / WATCHES / PREFERS / AVOIDS / EXPRESSED_VIEW / SOLD / STUDIED / COMPARED / BELONGS_TO / HAS_CONCEPT / CORRELATED_WITH

# Entity 命名规则
- Stock: entity_label = ts_code(如 '600519.SH')
- Industry: 申万二级
- Sector: 申万一级
- Metric/Strategy/Concept: 中英文混合白名单
- User: 固定 'User'

# importance 三档严格规则
- 0.9 (high): 用户明确强表态, 关键持仓 / 强偏好 / 强规避
- 0.5 (medium): 一般表达, 关注 / 一般观点 / 普通研究
- 0.2 (low): 暗示性 / 不确定 / 顺带提及
- **不允许其他值**

# 规则
- 只抽用户**显式表达**的事实
- "我之前 X 但现在 Y" → 抽两条 edge:
  - 第一条 valid_from=之前, valid_to=now()
  - 第二条 valid_from=now()
- 不确定标 importance=0.2

# 输出 JSON schema
{
  "entities": [{"entity_type": str, "entity_label": str, "properties": dict}],
  "edges": [{
      "rel_type": str,
      "source_label": str, "target_label": str,
      "valid_from": str, "valid_to": str | null,
      "importance": float,
      "reasoning": str,
      "properties": dict
  }]
}
**只输出 JSON, 不输出其他文字.**
"""

_EXTRACTION_USER_PROMPT_TEMPLATE = """\
# Episode (episode_id={episode_id})
User: {user_message}
Agent: {agent_response}
"""


class LLMExtractor:
    """spec § 4 Step 2 — LLM extraction 入口.

    Path A (agent-triggered, 半结构化) 也可走此, agent 已给 content/reasoning 时直接
    走 archival_memory_insert MCP tool wrapper (Plan 4) 跳过 LLM 抽.

    本 class 主要被 Path B (Plan 2B) end-of-session batch 调用.

    契约 ref: shared-contracts § 17 A2 (4) 双方法 — `extract` (Plan 2A) /
    `extract_facts` (Plan 2B 加跨轮抽取).
    """

    def __init__(
        self,
        llm_client: Any,  # ChatClient Protocol with .chat(prompt, ...)
        model: str = "claude-haiku-4.5",
        max_tokens: int = 2048,
    ) -> None:
        self._llm = llm_client
        self._model = model
        self._max_tokens = max_tokens

    async def extract(
        self,
        user_message: str,
        agent_response: str | None,
        episode_id: UUID,
    ) -> ExtractionOutput:
        """Run extraction on one episode, return ExtractionOutput.

        Raises ValueError for invalid JSON or schema validation failure.
        Caller (Path B Plan 2B) should fail-safe by catching and skipping.
        """
        prompt = _EXTRACTION_USER_PROMPT_TEMPLATE.format(
            episode_id=episode_id,
            user_message=user_message,
            agent_response=agent_response or "(no response)",
        )

        raw = await self._llm.chat(
            prompt=prompt,
            system=_EXTRACTION_SYSTEM_PROMPT,
            model=self._model,
            max_tokens=self._max_tokens,
        )

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            _logger.warning(
                "LLM extraction returned invalid JSON for episode_id=%s: %s",
                episode_id,
                raw[:200],
            )
            raise ValueError(f"invalid JSON from extraction LLM: {exc}") from exc

        return ExtractionOutput.model_validate(parsed)
