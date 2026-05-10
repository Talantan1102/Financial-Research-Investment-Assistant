"""L0 — Analyst honors chat_extracted_entities (comparative_target) + preferences.

Tests verify that build_analyst_prompt() injects comparative targets and
user preferences into the analyst prompt when chat signals are present (E13).
"""

from __future__ import annotations

from app.agents.analyst import build_analyst_prompt
from app.agents.escalation_protocol import Entity, Preference
from app.agents.schemas import ResearchState


def _make_state(**kwargs: object) -> ResearchState:
    defaults: dict[str, object] = {
        "user_id": "u",
        "session_id": "s",
        "user_message": "尽调 ICBC",
        "request_id": "r",
    }
    defaults.update(kwargs)
    return ResearchState(**defaults)  # type: ignore[arg-type]


def test_analyst_prompt_includes_comparative_targets() -> None:
    """Prompt must mention comparative_target entities and preferences (E13)."""
    state = _make_state(
        chat_extracted_entities=[
            Entity(
                name="工商银行",
                ts_code="601398.SH",
                role="primary_target",
                mention_turn_indices=[0],
            ),
            Entity(
                name="招商银行",
                ts_code="600036.SH",
                role="comparative_target",
                mention_turn_indices=[2],
            ),
        ],
        chat_extracted_preferences=[
            Preference(text="风控优先", category="risk_tolerance", confidence=0.9),
        ],
    )
    prompt = build_analyst_prompt(state)

    # Comparative target company name must appear in prompt
    assert "招商银行" in prompt

    # Must contain a comparative signal (English or Chinese)
    assert "comparative" in prompt.lower() or "对比" in prompt or "对标" in prompt

    # Preference text must appear in prompt
    assert "风控" in prompt or "risk" in prompt.lower()


def test_analyst_prompt_omits_block_when_no_chat_signals() -> None:
    """When no chat signals, comparative/preference blocks must not be injected."""
    state = _make_state()
    prompt = build_analyst_prompt(state)

    # Sanity: prompt is non-empty and contains the analyst header
    assert "analyst" in prompt

    # No chat-signal block headers injected
    assert "comparative_target" not in prompt
    assert "用户偏好" not in prompt
