"""C6 composite confidence — LLM self-report ∩ 5 deterministic features, take min.

Used by escalation router (Task 2.6) to decide whether to use distilled
multi-turn fields (escalation_intent / discussion_focus / explicit_exclusions)
or fall back to summary / form-style user_message.

Composite = min(LLM_self_mapped, avg_of_5_deterministic_features)

Rationale for min: any single layer doubting suffices to doubt overall (金融
fail-safe convention). LLM self-report is over-confidence-prone (Kadavath
et al 2022); deterministic features are rule-driven and miss nuance. Taking
min keeps both layers as veto gates.

spec ref: docs/superpowers/specs/2026-05-15-v1.x-plan-template-validator-design.md § 6.5
"""

from __future__ import annotations

from typing import Any, Protocol

from app.agents.escalation_protocol import EscalationPacket

__all__ = [
    "F_THRESHOLDS",
    "compute_confidence",
    "compute_deterministic_confidence",
]

_LLM_CONF_MAP: dict[str, float] = {"high": 0.9, "medium": 0.6, "low": 0.3}


F_THRESHOLDS: dict[str, Any] = {
    "chat_length_target": 5,
    "entity_density_target": 3,
    "explicit_keywords": frozenset(
        {
            "尽调",
            "深度分析",
            "详细看看",
            "全面研究",
            "深入研究",
            "做个调研",
        }
    ),
    "contradiction_pairs": (
        ("买入", "卖出"),
        ("加仓", "减仓"),
        ("做多", "做空"),
        ("看多", "看空"),
        ("乐观", "悲观"),
    ),
}


class _ChatMsgLike(Protocol):
    content: str


def _f1_chat_length(history: list[_ChatMsgLike]) -> float:
    target = F_THRESHOLDS["chat_length_target"]
    return min(len(history) / target, 1.0)


def _f2_entity_density(history: list[_ChatMsgLike], ts_code: str, target_name: str) -> float:
    mentions = sum(
        1
        for m in history
        if (ts_code and ts_code in m.content) or (target_name and target_name in m.content)
    )
    target = F_THRESHOLDS["entity_density_target"]
    return min(mentions / target, 1.0)


def _f3_explicit_intent(history: list[_ChatMsgLike]) -> float:
    recent = history[-3:] if len(history) >= 3 else history
    keywords = F_THRESHOLDS["explicit_keywords"]
    return 1.0 if any(kw in m.content for m in recent for kw in keywords) else 0.6


def _has_contradiction(focus: list[str]) -> bool:
    joined = " ".join(focus)
    return any(a in joined and b in joined for a, b in F_THRESHOLDS["contradiction_pairs"])


def _f4_no_contradiction(extracted: EscalationPacket) -> float:
    return 0.3 if _has_contradiction(extracted.discussion_focus) else 1.0


def _f5_explicit_confirm(user_confirmed: bool) -> float:
    return 1.0 if user_confirmed else 0.7


def compute_deterministic_confidence(
    extracted: EscalationPacket,
    chat_history: list[Any],
    target_ts_code: str,
    target_name: str,
    user_confirmed_escalation: bool,
) -> float:
    """Average of 5 deterministic features (each ∈ [0.0, 1.0])."""
    features = {
        "chat_length": _f1_chat_length(chat_history),
        "entity_density": _f2_entity_density(chat_history, target_ts_code, target_name),
        "explicit_intent": _f3_explicit_intent(chat_history),
        "no_contradiction": _f4_no_contradiction(extracted),
        "explicit_confirm": _f5_explicit_confirm(user_confirmed_escalation),
    }
    return sum(features.values()) / len(features)


def compute_confidence(
    extracted: EscalationPacket,
    chat_history: list[Any],
    target_ts_code: str,
    target_name: str,
    user_confirmed_escalation: bool,
) -> float:
    """Composite — min(LLM self-report mapped, deterministic average).

    Either layer doubting suffices to doubt overall. Fail-safe金融场景 convention.
    """
    llm = _LLM_CONF_MAP[extracted.llm_self_confidence]
    det = compute_deterministic_confidence(
        extracted,
        chat_history,
        target_ts_code,
        target_name,
        user_confirmed_escalation,
    )
    return min(llm, det)
