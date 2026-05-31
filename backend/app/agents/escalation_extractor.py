"""EscalationExtractor — LLM-fill EscalationPacket draft (E9)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from app.agents.escalation_protocol import (
    ChatDerivedSignals,
    EscalationPacket,
    ExplicitTask,
    KnownFacts,
    MissingFieldHint,
    SessionMetadata,
)
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)


_EXTRACTOR_PROMPT_TEMPLATE = """\
你是金融研究助手 chat→research 升级通道的「信号抽取员」。
用户在 chat 模式聊了多轮后,触发了「深度研报」按钮。你要看完整对话,
帮 ResearchAgent 准备好结构化的 EscalationPacket 草稿。
然后用户会确认/修改你写的草稿,所以**不确定的地方要标 missing_field_hints**,不要瞎猜。

==== 输入 ====

【chat session id】{chat_session_id}
【已聊的轮数】{chat_turn_count}
【历史摘要】{chat_history_summary}

【完整对话历史】
{history_block}

【chat 期间已查过的工具结果】
{cached_block}

==== 输出 ====

严格按下列 JSON 输出,不要任何额外文字、代码块或注释:
{{
  "explicit_task": {{
    "raw_last_user_turn": "...",
    "extracted_intent": "...",
    "target_ts_code": "..." or null,
    "target_entity_name": "..." or null,
    "user_extra_message": null
  }},
  "chat_derived_signals": {{
    "entities": [...],
    "preferences": [...],
    "open_questions": [...],
    "inferred_persona": "..." or null,
    "extraction_confidence": float in [0, 1]
  }},
  "known_facts": {{"tool_results": [...]}},
  "session_metadata": {{
    "chat_session_id": "{chat_session_id}",
    "chat_turn_count": {chat_turn_count},
    "chat_history_summary": ... or null,
    "user_confirmed_at": "{now_iso}",
    "user_edits": []
  }},
  "missing_field_hints": [...],
  "escalation_intent": "<≤200 字, 蒸馏用户的核心尽调请求>",
  "discussion_focus": ["≤30 字 焦点 1", "焦点 2", "..."],
  "explicit_exclusions": ["≤30 字 排除项 1", "..."],
  "llm_self_confidence": "high|medium|low",
  "confidence_rationale": "<≤100 字 解释>"
}}

注: discussion_focus 最多 5 条; explicit_exclusions 最多 3 条。

==== 工程约束 ====

1. 不许编造 cache_id — 必须严格来自上面【chat 期间已查过的工具结果】。
2. 不确定就标 missing_field_hints。
3. preferences 必须从对话中能找到证据。
4. extraction_confidence 反映自己的把握。
5. escalation_intent: 从最后 5 轮聚焦, 蒸馏用户为什么想做尽调 (不是闲聊主题)。≤200 字。
6. discussion_focus: 对话中反复出现的关注点 — 例 "客户担心负债率" / "对比五粮液"。每条 ≤30 字, 最多 5 条。
7. explicit_exclusions: 用户明确表达不关注 / 不在意的方面 — 例 "不关心 ESG" / "不看技术面"。每条 ≤30 字, 最多 3 条。
8. llm_self_confidence: high (对话明确 + 5+ 轮 + entity 频繁) / medium / low (对话短或前后矛盾)。
9. confidence_rationale: ≤100 字解释自己的把握来源 — 帮助用户判断是否要 override。
"""


def _format_history(history: list[dict[str, Any]]) -> str:
    if not history:
        return "(空)"
    lines = []
    for i, t in enumerate(history):
        role = t.get("role", "?")
        content = (t.get("content") or "")[:500]
        lines.append(f"[turn {i}] {role}: {content}")
    return "\n".join(lines)


def _format_cached_tools(cached: list[dict[str, Any]]) -> str:
    if not cached:
        return "(无)"
    lines = []
    for c in cached:
        lines.append(
            f"- {c.get('tool_name')}({json.dumps(c.get('tool_args', {}), ensure_ascii=False)}) "
            f"→ {c.get('result_summary', '')[:200]}  [cache_id={c.get('cache_id')}]"
        )
    return "\n".join(lines)


class EscalationExtractor:
    def __init__(self, llm: LLMService) -> None:
        self._llm = llm

    async def run(
        self,
        *,
        chat_session_id: str,
        chat_turn_count: int,
        chat_history_summary: str | None,
        history: list[dict[str, Any]],
        cached_tool_results: list[dict[str, Any]],
        request_id: str | None = None,  # C26: thread originating request for span linkage
    ) -> EscalationPacket:
        now_iso = datetime.now(UTC).isoformat()
        prompt = _EXTRACTOR_PROMPT_TEMPLATE.format(
            chat_session_id=chat_session_id,
            chat_turn_count=chat_turn_count,
            chat_history_summary=chat_history_summary or "(无)",
            history_block=_format_history(history),
            cached_block=_format_cached_tools(cached_tool_results),
            now_iso=now_iso,
        )
        resp = self._llm.chat(prompt=prompt, tier="fast", schema=None, request_id=request_id)

        try:
            data = json.loads(resp.content)
        except (json.JSONDecodeError, AttributeError):
            logger.warning("EscalationExtractor: LLM returned non-JSON; minimal fallback")
            return self._minimal_fallback(
                chat_session_id,
                chat_turn_count,
                history,
                cached_tool_results,
            )

        # Filter hallucinated cache_ids — only allow cache_ids from the actual input
        valid_cache_ids = {c.get("cache_id") for c in cached_tool_results}
        if "known_facts" in data and "tool_results" in data["known_facts"]:
            data["known_facts"]["tool_results"] = [
                tr
                for tr in data["known_facts"]["tool_results"]
                if tr.get("cache_id") in valid_cache_ids
            ]

        try:
            return EscalationPacket.model_validate(data)
        except ValidationError as e:
            # C61: narrow to ValidationError — genuine schema mismatch → minimal fallback;
            # TypeError/AttributeError (structurally malformed data) must propagate loudly.
            logger.warning("EscalationExtractor: Pydantic validation failed: %s", e)
            return self._minimal_fallback(
                chat_session_id,
                chat_turn_count,
                history,
                cached_tool_results,
            )

    def _minimal_fallback(
        self,
        chat_session_id: str,
        chat_turn_count: int,
        history: list[dict[str, Any]],
        cached_tool_results: list[dict[str, Any]],
    ) -> EscalationPacket:
        last_user = ""
        for t in reversed(history):
            if t.get("role") == "user":
                last_user = t.get("content", "")
                break
        return EscalationPacket(
            explicit_task=ExplicitTask(
                raw_last_user_turn=last_user,
                extracted_intent="unknown",
            ),
            chat_derived_signals=ChatDerivedSignals(
                extraction_confidence=0.0,
            ),
            known_facts=KnownFacts(),
            session_metadata=SessionMetadata(
                chat_session_id=chat_session_id,
                chat_turn_count=chat_turn_count,
                user_confirmed_at=datetime.now(UTC),
            ),
            missing_field_hints=[
                MissingFieldHint(
                    field_path="explicit_task.extracted_intent",
                    reason="llm_uncertain",
                    llm_question_for_user="抱歉, 我没能从对话中提取清晰的研究意图。请用一句话告诉我您想研究什么 (例如: '工商银行 (601398.SH) 的完整投资尽调')",
                ),
            ],
        )
