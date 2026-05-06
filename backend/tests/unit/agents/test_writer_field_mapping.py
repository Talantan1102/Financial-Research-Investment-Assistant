"""Unit tests — Writer build_investment_dd_prompt 6-field conditioning.

v0.8.5 — calc_recommended_position_size_pct removed (replaced by skill bundle
compute_position_size_pct, tested separately in
backend/tests/unit/skills/test_compute_position_size.py). The position-size
calculator tests that lived here previously are now redundant; only prompt-
conditioning tests remain.

spec ref: docs/superpowers/specs/2026-05-04-v0.8.4-b1-single-deep-design.md § 5.3
spec ref: docs/superpowers/specs/2026-05-04-v0.8.5-constrained-router-design.md § Task 5
"""

from __future__ import annotations

import pytest
from app.agents.schemas import ResearchState
from app.agents.writer import build_investment_dd_prompt


def _make_state(**kwargs: object) -> ResearchState:
    defaults: dict[str, object] = {
        "user_id": "test",
        "session_id": "sess-1",
        "user_message": "请对贵州茅台进行投资尽调。",
        "request_id": "req-1",
        "target_ts_code": "600519.SH",
        "client_total_aum": 10_000_000.0,
        "investment_objective": "balanced",
        "investment_horizon": "medium_term",
        "risk_tolerance": "moderate",
    }
    defaults.update(kwargs)
    return ResearchState(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tests for build_investment_dd_prompt — 6-field conditioning
# ---------------------------------------------------------------------------


def test_writer_prompt_contains_investment_objective() -> None:
    """Writer prompt 必须包含 investment_objective 字段。"""
    state = _make_state(investment_objective="capital_preservation")
    prompt = build_investment_dd_prompt(state)
    assert "capital_preservation" in prompt or "保本" in prompt


def test_writer_prompt_contains_risk_tolerance() -> None:
    """Writer prompt 必须包含 risk_tolerance 字段。"""
    state = _make_state(risk_tolerance="very_aggressive")
    prompt = build_investment_dd_prompt(state)
    assert "very_aggressive" in prompt or "激进" in prompt


def test_writer_prompt_contains_investment_horizon() -> None:
    """Writer prompt 必须包含 investment_horizon 字段。"""
    state = _make_state(investment_horizon="long_term")
    prompt = build_investment_dd_prompt(state)
    assert "long_term" in prompt or "长期" in prompt


def test_writer_prompt_contains_aum() -> None:
    """Writer prompt 必须包含 client_total_aum 数字(用于仓位计算说明)。"""
    state = _make_state(client_total_aum=50_000_000.0)
    prompt = build_investment_dd_prompt(state)
    # AUM 应以某种形式出现在 prompt 中
    assert "50000000" in prompt or "5000" in prompt or "AUM" in prompt or "总资产" in prompt


def test_writer_prompt_contains_position_size_constraint() -> None:
    """Writer prompt 必须包含 § 6 仓位约束引导词。"""
    state = _make_state(risk_tolerance="conservative")
    prompt = build_investment_dd_prompt(state)
    # prompt 应提及仓位 / position_size / § 6 相关
    assert (
        "仓位" in prompt or "position_size" in prompt or "recommended_position_size_pct" in prompt
    )


@pytest.mark.parametrize(
    "objective", ["capital_preservation", "stable_growth", "balanced", "aggressive_growth"]
)
def test_writer_prompt_all_objectives_nonempty(objective: str) -> None:
    """所有 investment_objective 值都应产生非空 prompt。"""
    state = _make_state(investment_objective=objective)
    prompt = build_investment_dd_prompt(state)
    assert isinstance(prompt, str) and len(prompt) > 500
