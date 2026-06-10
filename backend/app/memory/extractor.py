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
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.memory.extraction_guards import is_stance_phrase_label, sanitize_edge
from app.memory.registry import REL_TYPES

_logger = logging.getLogger(__name__)


def _latest_turn_date(turns: list[dict[str, Any]]) -> datetime:
    """chunk 的"现在"=最晚一个 turn 的对话日期,作幻觉 valid_to 的越界基准。"""
    dates: list[datetime] = []
    for t in turns:
        raw = str(t.get("created_at") or "")
        try:
            dates.append(datetime.fromisoformat(raw.replace("Z", "+00:00")))
        except (ValueError, TypeError):
            continue
    return max(dates) if dates else datetime.now(UTC)


def _build_output_tolerant(
    parsed: dict[str, Any],
    *,
    episode_date: datetime,
    session_id: UUID,
) -> ExtractionOutput:
    """逐边/逐实体容错构造 ExtractionOutput:一条坏边/脏实体丢弃留痕,不毁整批。

    对话流评估写侧根因之一:pydantic 对 list 是 all-or-nothing,一条非法 rel_type
    让整 chunk 抽取全灭、事实尽失。改成逐元素校验 + 后校验护栏(脏 label 丢弃、
    幻觉 valid_to 重置)。
    """
    good_entities: list[ExtractedEntity] = []
    for e in parsed.get("entities", []) or []:
        try:
            good_entities.append(ExtractedEntity.model_validate(e))
        except ValidationError as exc:
            _logger.warning("extract_facts drop bad entity (session=%s): %s", session_id, exc)

    good_edges: list[ExtractedEdge] = []
    for raw_edge in parsed.get("edges", []) or []:
        if not isinstance(raw_edge, dict):
            continue
        if is_stance_phrase_label(str(raw_edge.get("target_label", ""))):
            _logger.warning(
                "extract_facts drop stance-phrase label (session=%s): %s",
                session_id,
                raw_edge.get("target_label"),
            )
            continue
        sanitized = sanitize_edge(raw_edge, episode_date=episode_date)
        try:
            good_edges.append(ExtractedEdge.model_validate(sanitized))
        except ValidationError as exc:
            _logger.warning("extract_facts drop bad edge (session=%s): %s", session_id, exc)

    return ExtractionOutput(entities=good_entities, edges=good_edges)


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
- 不确定标 importance=0.2

# 实体类型与关系裁决(必须照此判,别自由发挥)
## target 实体类型怎么选(看用户表态的主体粒度)
- 用户对一个行业/板块的看法 → target 用 Industry(申万二级,如"白酒"→"白酒Ⅱ")
- 用户对一只具体个股的看法 → target 用 Stock(ts_code)
- 用户只说板块(如"高端白酒")时,【不要替他补】具体个股(茅台/五粮液只是举例,不单独建观点边)
- 逻辑/主题(如"提价权")放进该观点边的 properties.logic,【不要】单独建一条边
## 关系怎么选(照表挑,别随机)
- 有方向词(看多/看空/中性/高估/低估)+具体对象 → EXPRESSED_VIEW
- 跨标的的风格/策略偏好(喜欢价值/高股息) → PREFERS
- 不碰/排斥某类 → AVOIDS;关注但没下判断 → WATCHES;研究过 → STUDIED;持仓 → HOLDS;卖出 → SOLD
- "看多白酒"【必为 EXPRESSED_VIEW,绝不可标 PREFERS】
## entity_label 形态
- 必须是名词性实体(如 白酒Ⅱ / 600519.SH),【禁】"看多/看空/买入…"开头的整句谓词短语

# 日期纪律(必须遵守)
- 每个 episode 的【对话日期】已在输入里给出,valid_from 必须等于对应对话日期,【不许假设/编造日期】
- 观点未结束时 valid_to 必须为 null
- "我之前 X 但现在 Y"(同一对象观点演化)→ 抽两条 edge:
  - 旧的一条 valid_to = 说出"现在 Y"那 turn 的对话日期
  - 新的一条 valid_from = 说出"现在 Y"那 turn 的对话日期、valid_to=null

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

        S1 fix — episode 文本过 injection 分类器, 命中返空 ExtractionOutput
        (不 raise, 避免阻塞 caller; spec § 11 末尾 #2 part a 死代码修复).
        """
        from app.memory.injection_classifier import is_prompt_injection

        combined = (user_message or "") + "\n" + (agent_response or "")
        is_inj, conf, pattern_id = is_prompt_injection(combined)
        if is_inj:
            _logger.warning(
                "LLMExtractor.extract skipped episode_id=%s flagged as prompt injection "
                "(pattern=%s, confidence=%.2f)",
                episode_id,
                pattern_id,
                conf,
            )
            return ExtractionOutput(entities=[], edges=[])

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

    async def extract_facts(
        self,
        turns: list[dict[str, Any]],
        session_id: UUID,
        episode_ids: list[UUID],
    ) -> list[ExtractionOutput]:
        """Plan 2B Path B 跨轮 5 turn 滑动窗口 — 1 chunk 1 LLM call.

        Per shared contract § 17 A2 (4): turns 是 build_sliding_window 输出的
        list[dict] (each: episode_id / episode_index / user_message / agent_response /
        created_at), session_id + episode_ids 用作 audit / source_episode_id 关联.

        返回 list[ExtractionOutput] (Plan 2B 单 chunk 一次 LLM call → list 长度 1;
        Plan 5 升级 batch 时长度 = 输入 episode 数). 不抛 — invalid JSON / schema
        验证失败 raise ValueError, caller (PathBRunner) 走 failure_matrix.

        S1 fix — chunk 内任一 turn 命中 injection 分类器 → 整 chunk 返空 list
        (保守; 一颗老鼠屎污染整 chunk 的语义上下文, 不冒险只剔单 turn).
        """
        from app.memory.injection_classifier import is_prompt_injection

        if not turns:
            return []

        for t in turns:
            combined = (
                str(t.get("user_message", "") or "") + "\n" + str(t.get("agent_response", "") or "")
            )
            is_inj, conf, pattern_id = is_prompt_injection(combined)
            if is_inj:
                _logger.warning(
                    "LLMExtractor.extract_facts skipped chunk session=%s "
                    "(injection in episode_id=%s pattern=%s confidence=%.2f)",
                    session_id,
                    t.get("episode_id"),
                    pattern_id,
                    conf,
                )
                return []

        prompt = _build_cross_turn_user_prompt(turns, session_id=session_id)
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
                "LLM cross-turn extraction returned invalid JSON for session=%s: %s",
                session_id,
                raw[:200],
            )
            raise ValueError(f"invalid JSON from cross-turn extraction LLM: {exc}") from exc

        # Plan 2B: 1 chunk → 1 ExtractionOutput;逐边容错 + 后校验护栏
        chunk_now = _latest_turn_date(turns)
        return [_build_output_tolerant(parsed, episode_date=chunk_now, session_id=session_id)]


def _build_cross_turn_user_prompt(
    turns: list[dict[str, Any]],
    *,
    session_id: UUID,
) -> str:
    """构造 5 turn 滑动窗口 prompt 输入 — 让 LLM 跨 turn 抽完整 fact."""
    lines: list[str] = [f"# Cross-turn dialogue chunk (session_id={session_id})"]
    lines.append("最近 N turn 对话 (按时间序), 抽出跨 turn 完整事实。")
    lines.append("每个 turn 标了【对话日期】,valid_from 必须用对应对话日期,不许编造:")
    for t in turns:
        # 对话日期注入:抽取器据此钉 valid_from,杜绝幻觉日期(取 created_at 的日期部分)
        created = str(t.get("created_at") or "")
        dialogue_date = created[:10] if created else "(未知)"
        lines.append(
            f"- episode_id={t.get('episode_id')} idx={t.get('episode_index')} 对话日期={dialogue_date}"
            f"\n  User: {t.get('user_message', '')}"
            f"\n  Agent: {t.get('agent_response', '') or '(no response)'}"
        )
    lines.append(
        "\n注意: 跨 turn 把'我刚买了 → 买什么 → 茅台 500 股'拼成完整 HOLDS edge "
        "(qty 写 properties); 单 turn fact 不退化."
    )
    return "\n".join(lines)
