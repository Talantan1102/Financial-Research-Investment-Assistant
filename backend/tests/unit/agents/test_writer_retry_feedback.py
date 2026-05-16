"""Writer prompt — writer_critic_feedback injection on retry (v1.x)."""

from __future__ import annotations


def _mk_state(**kw):
    from app.agents.schemas import ResearchState

    base = {
        "user_id": "u",
        "session_id": "s",
        "user_message": "m",
        "request_id": "r",
        "target_ts_code": "600519.SH",
        "investment_objective": "balanced",
        "investment_horizon": "medium_term",
        "risk_tolerance": "moderate",
        "client_total_aum": 1_000_000.0,
    }
    base.update(kw)
    return ResearchState(**base)


def test_writer_prompt_no_feedback_block_when_field_empty() -> None:
    """First attempt (no retry) → no Critic feedback section."""
    from app.agents.writer import build_investment_dd_prompt

    state = _mk_state()
    prompt = build_investment_dd_prompt(state)
    assert "Critic 反馈" not in prompt
    assert "上一轮 factuality" not in prompt


def test_writer_prompt_no_feedback_block_when_field_none() -> None:
    """Explicit None → no feedback."""
    from app.agents.writer import build_investment_dd_prompt

    state = _mk_state(writer_critic_feedback=None)
    prompt = build_investment_dd_prompt(state)
    assert "Critic 反馈" not in prompt


def test_writer_prompt_includes_feedback_when_present() -> None:
    """writer_critic_feedback set → prompt injects feedback section."""
    from app.agents.writer import build_investment_dd_prompt

    feedback = "§ 3 财务节引用了不存在的 chunk_id ch_999"
    state = _mk_state(writer_critic_feedback=feedback)
    prompt = build_investment_dd_prompt(state)
    assert "ch_999" in prompt
    assert feedback in prompt
    # The feedback block should clearly signal retry context to the LLM
    assert "Critic" in prompt
    assert "factuality" in prompt.lower()


def test_writer_prompt_feedback_instructs_evidence_fix() -> None:
    """Feedback block should tell LLM to fix evidence/chunk_id issues."""
    from app.agents.writer import build_investment_dd_prompt

    state = _mk_state(writer_critic_feedback="bad citation")
    prompt = build_investment_dd_prompt(state)
    # Some instruction about checking evidence / chunk_id / 引用 / 真实
    assert (
        "evidence" in prompt.lower()
        or "chunk_id" in prompt.lower()
        or "引用" in prompt
        or "真实" in prompt
    )


def test_writer_prompt_feedback_block_uses_state_value_verbatim() -> None:
    """No prefix mangling — the feedback text itself appears in prompt."""
    from app.agents.writer import build_investment_dd_prompt

    state = _mk_state(writer_critic_feedback="特定字符串 abc123 标识")
    prompt = build_investment_dd_prompt(state)
    assert "特定字符串 abc123 标识" in prompt
