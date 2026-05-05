"""Verify Analyst prompt 注入 SOP 11 维度关键词 (v0.8.5).

spec ref: docs/superpowers/specs/2026-05-04-v0.8.5-constrained-router-design.md § Task 5
"""

from __future__ import annotations

from app.agents.analyst import build_analyst_prompt
from app.agents.schemas import ResearchState


def _make_state(**kwargs: object) -> ResearchState:
    defaults: dict[str, object] = {
        "user_id": "test",
        "session_id": "sess-1",
        "user_message": "请对贵州茅台进行投资分析。",
        "request_id": "req-1",
        "target_ts_code": "600519.SH",
        "client_total_aum": 10_000_000.0,
        "investment_objective": "balanced",
        "investment_horizon": "medium_term",
        "risk_tolerance": "moderate",
    }
    defaults.update(kwargs)
    return ResearchState(**defaults)  # type: ignore[arg-type]


_SOP_KEYWORDS_11 = [
    "偿债",
    "盈利",
    "成长",
    "现金流",
    "估值",
    "行业",
    "股东",
    "资金流",
    "事件",
    "风险",
    "决策",
]


def test_analyst_prompt_contains_sop_11_keywords() -> None:
    """SOP 11 维度关键词必须全部出现在 analyst prompt 中。"""
    state = _make_state()
    prompt = build_analyst_prompt(state)
    for kw in _SOP_KEYWORDS_11:
        assert kw in prompt, f"prompt missing SOP keyword: {kw}"


def test_analyst_prompt_contains_sop_section_header() -> None:
    """Prompt 必须含 SOP section header,标识 11 维度方法论已注入。"""
    state = _make_state()
    prompt = build_analyst_prompt(state)
    assert "投资研究员 SOP" in prompt or "11 维度方法论" in prompt


def test_analyst_prompt_sop_injection_idempotent() -> None:
    """同一 state 两次调用 prompt 内容一致 (deterministic)。"""
    state = _make_state()
    p1 = build_analyst_prompt(state)
    p2 = build_analyst_prompt(state)
    assert p1 == p2
