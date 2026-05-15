"""C6 composite confidence (LLM self ∩ 5 deterministic features, take min)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from app.agents.escalation_confidence import (
    _LLM_CONF_MAP,
    F_THRESHOLDS,
    compute_confidence,
    compute_deterministic_confidence,
)
from app.agents.escalation_protocol import (
    ChatDerivedSignals,
    EscalationPacket,
    ExplicitTask,
    KnownFacts,
    SessionMetadata,
)


@dataclass
class _Msg:
    content: str


def _mk_packet(focus: list[str] | None = None, llm_self: str = "high"):
    return EscalationPacket(
        explicit_task=ExplicitTask(raw_last_user_turn="x", extracted_intent="y"),
        chat_derived_signals=ChatDerivedSignals(extraction_confidence=0.8),
        known_facts=KnownFacts(),
        session_metadata=SessionMetadata(
            chat_session_id="s", chat_turn_count=5,
            user_confirmed_at=datetime.now(UTC),
        ),
        escalation_intent="x",
        discussion_focus=focus or [],
        explicit_exclusions=[],
        llm_self_confidence=llm_self,
        confidence_rationale="r",
    )


def _full_chat(target_ts: str = "600519.SH", target_name: str = "贵州茅台", n: int = 5,
               keyword: str = "尽调") -> list[_Msg]:
    """Full positive-signal chat — 5 turns, lots of target mentions, has keyword."""
    msgs = [_Msg(f"{target_ts} {target_name} 怎么样") for _ in range(n - 1)]
    msgs.append(_Msg(f"帮我做个 {keyword}"))
    return msgs


# ─── LLM map ────────────────────────────────────────────────────────────


def test_llm_conf_map_values() -> None:
    assert _LLM_CONF_MAP == {"high": 0.9, "medium": 0.6, "low": 0.3}


def test_f_thresholds_exported() -> None:
    """F_THRESHOLDS is part of the public API surface (tuning knob)."""
    assert "尽调" in F_THRESHOLDS["explicit_keywords"]
    assert F_THRESHOLDS["chat_length_target"] == 5
    assert F_THRESHOLDS["entity_density_target"] == 3
    assert ("买入", "卖出") in F_THRESHOLDS["contradiction_pairs"]


# ─── Individual features ────────────────────────────────────────────────


def test_f1_chat_length_short_low() -> None:
    """≤2 turns → F1 = 2/5 = 0.4."""
    hist = [_Msg("hi"), _Msg("ok")]
    conf = compute_deterministic_confidence(
        _mk_packet(), hist, "600519.SH", "贵州茅台", True,
    )
    # F1=0.4, F2=0 (no mentions), F3=0.6 (no keyword), F4=1.0, F5=1.0
    # avg = (0.4 + 0 + 0.6 + 1 + 1) / 5 = 0.6
    assert conf < 0.7


def test_f2_entity_density_zero() -> None:
    """0 target mentions → F2 = 0 (drags composite down)."""
    hist = [_Msg("聊点别的") for _ in range(5)]
    conf = compute_deterministic_confidence(
        _mk_packet(), hist, "600519.SH", "贵州茅台", True,
    )
    # F1=1, F2=0, F3=0.6, F4=1, F5=1 → avg=0.72
    assert conf < 0.8


def test_f2_entity_density_high() -> None:
    """3+ mentions → F2 = 1.0."""
    hist = _full_chat()
    conf = compute_deterministic_confidence(
        _mk_packet(), hist, "600519.SH", "贵州茅台", True,
    )
    # F1=1, F2=1, F3=1, F4=1, F5=1 → avg=1.0
    assert conf == pytest.approx(1.0)


def test_f3_explicit_keyword_boost() -> None:
    with_kw = [_Msg("贵州茅台"), _Msg("好"), _Msg("帮我做个尽调")]
    no_kw = [_Msg("贵州茅台"), _Msg("好"), _Msg("帮我看看")]
    a = compute_deterministic_confidence(_mk_packet(), with_kw, "600519.SH", "贵州茅台", True)
    b = compute_deterministic_confidence(_mk_packet(), no_kw, "600519.SH", "贵州茅台", True)
    assert a > b


def test_f3_keyword_in_recent_turns_only() -> None:
    """Keyword in OLD turn (not last 3) does NOT trigger F3=1.0."""
    hist = [
        _Msg("尽调"),  # turn 0 — OLD, ignored
        _Msg("贵州茅台"), _Msg("贵州茅台"), _Msg("贵州茅台"),
        _Msg("近期表现"),  # turn 4 — recent, no keyword
    ]
    conf = compute_deterministic_confidence(_mk_packet(), hist, "600519.SH", "贵州茅台", True)
    # F3 should be 0.6 (no keyword in last 3 turns)
    # Compute: F1=1, F2=1, F3=0.6, F4=1, F5=1 → avg=0.92
    assert conf == pytest.approx(0.92, abs=0.01)


def test_f4_contradiction_penalty() -> None:
    contradict = _mk_packet(focus=["想买入", "想卖出"])
    clean = _mk_packet(focus=["关心 ROE"])
    hist = _full_chat()
    a = compute_deterministic_confidence(clean, hist, "600519.SH", "贵州茅台", True)
    b = compute_deterministic_confidence(contradict, hist, "600519.SH", "贵州茅台", True)
    assert a > b


def test_f4_contradiction_pairs() -> None:
    """Multiple contradiction pairs detected."""
    hist = _full_chat()
    for pair in [("买入", "卖出"), ("加仓", "减仓"), ("做多", "做空"), ("看多", "看空"), ("乐观", "悲观")]:
        focus = [f"想{pair[0]}", f"也想{pair[1]}"]
        conf = compute_deterministic_confidence(
            _mk_packet(focus=focus), hist, "600519.SH", "贵州茅台", True,
        )
        # F4=0.3 (contradiction) → avg = (1+1+1+0.3+1)/5 = 0.86
        assert conf == pytest.approx(0.86, abs=0.01), f"pair {pair}: {conf}"


def test_f5_explicit_confirm_boost() -> None:
    hist = _full_chat()
    confirmed = compute_deterministic_confidence(_mk_packet(), hist, "600519.SH", "贵州茅台", True)
    not_confirmed = compute_deterministic_confidence(_mk_packet(), hist, "600519.SH", "贵州茅台", False)
    assert confirmed > not_confirmed
    # F5 difference: 1.0 vs 0.7 → 0.3 / 5 = 0.06 avg diff
    assert (confirmed - not_confirmed) == pytest.approx(0.06, abs=0.01)


# ─── Composite (take min) ───────────────────────────────────────────────


def test_composite_takes_min_llm_low_overrides_det_high() -> None:
    """LLM self=low (0.3) overrides high deterministic → composite = 0.3."""
    hist = _full_chat()  # all features 1.0 → det=1.0
    packet = _mk_packet(llm_self="low")
    conf = compute_confidence(packet, hist, "600519.SH", "贵州茅台", True)
    assert conf == 0.3


def test_composite_takes_min_det_low_overrides_llm_high() -> None:
    """Deterministic low (short chat, no entity) → composite = det, not LLM 0.9."""
    hist = [_Msg("hi"), _Msg("ok")]  # F1=0.4, F2=0
    packet = _mk_packet(llm_self="high")
    conf = compute_confidence(packet, hist, "600519.SH", "贵州茅台", False)
    assert conf < 0.9
    # det = avg(0.4, 0, 0.6, 1, 0.7) / 5 = 0.54 → min(0.9, 0.54) = 0.54
    assert conf == pytest.approx(0.54, abs=0.01)


def test_composite_perfect_case() -> None:
    """Both LLM and det say high → composite = min(0.9, 1.0) = 0.9."""
    hist = _full_chat()
    packet = _mk_packet(llm_self="high")
    conf = compute_confidence(packet, hist, "600519.SH", "贵州茅台", True)
    assert conf == pytest.approx(0.9)
