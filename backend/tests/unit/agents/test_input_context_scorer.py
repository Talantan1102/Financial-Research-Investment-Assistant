"""Unit tests for InputContextAppropriatenessScorer (Critic 第 6 scorer, v0.8.4).

Tests use a mock LLMService (no real network calls, no cassette).
LLM_MODE is set to "mock" by autouse fixture in conftest.py hierarchy — but
since we bypass LLMService by injecting a MagicMock, we need LLM_MODE != "none"
to avoid the RuntimeError guard in LLMService.__init__. We patch BEFORE
constructing LLMService.

spec ref: docs/superpowers/specs/2026-05-04-v0.8.4-b1-single-deep-design.md § 4 / § 7
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from app.agents.critic_subagents.input_context_scorer import (
    InputContextAppropriatenessScorer,
)
from app.agents.schemas import ResearchState
from app.services.llm_response import LLMResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_llm(response_content: str) -> MagicMock:
    """Return a MagicMock that implements LLMService.chat() protocol."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = LLMResponse(
        content=response_content,
        parsed=None,
        model="qwen-turbo",
        tier="fast",
        prompt_tokens=200,
        completion_tokens=50,
        total_tokens=250,
        cost_cny=0.001,
        latency_ms=100,
        request_id="req-mock-001",
    )
    return mock_llm


def _make_state(**kwargs: object) -> ResearchState:
    defaults: dict[str, object] = {
        "user_id": "test",
        "session_id": "sess-test",
        "user_message": "请对贵州茅台(600519.SH)进行投资尽调。",
        "request_id": "req-test-001",
        "target_ts_code": "600519.SH",
        "client_total_aum": 10_000_000.0,
        "investment_objective": "balanced",
        "investment_horizon": "medium_term",
        "risk_tolerance": "moderate",
    }
    defaults.update(kwargs)
    return ResearchState(**defaults)  # type: ignore[arg-type]


_WELL_ALIGNED_REPORT = """
# 投资标的尽调报告 — 贵州茅台酒股份有限公司 (600519.SH)

## § 6 投资建议

基于您的**均衡型**(balanced)投资目标和**中等风险承受度**(moderate),
本报告建议对茅台保持适度增持立场。

在投资期限方面,中期(medium_term)视角下茅台的估值回归逻辑清晰,
建议持有 6-18 个月。

**建议仓位:占 AUM 的 8.0%**

止损价: 1,580元。建议仓位管理条件:
- 若市场系统性回调超过 5% 时小批量加仓
- 若估值突破历史高位 PE 则减仓至 4%

风险提示:在 moderate 风险承受度下,需重点关注估值风险和行业政策变化。
均衡型投资者应同时考量价值保护和适度成长机会。
""".strip()

_GENERIC_BOILERPLATE_REPORT = """
# 贵州茅台(600519.SH)投资分析报告

## 公司概况

贵州茅台酒股份有限公司是中国高端白酒行业龙头企业。

## 财务分析

茅台2024年实现营业收入1782亿元,净利润857亿元,ROE 33.5%。

## 投资建议

综合公司基本面、行业前景和估值,建议持有。
建议仓位:5%。持有期:中长期。
""".strip()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_force_llm_mode_mock")
def test_scorer_high_score_for_well_aligned_report(monkeypatch: pytest.MonkeyPatch) -> None:
    """well-aligned 报告:内容显式引用 6 字段 → mock LLM 返回高分 → score ≥ 8.5。

    The scorer passes the 6 input fields + report_markdown to the judge LLM.
    This test mocks the LLM to return score=9.0, simulating what a real judge
    would return for a well-aligned report. The assertion verifies the scorer
    correctly parses the 0-10 score and stores it in the StepResult.
    """
    monkeypatch.setenv("LLM_MODE", "mock")

    high_score_response = '{"score": 9.0, "evidence": "报告明确引用 balanced 目标和 moderate 风险偏好;仓位 8% 与风险等级匹配;中期持有期与 medium_term 一致。"}'
    mock_llm = _make_mock_llm(high_score_response)

    scorer = InputContextAppropriatenessScorer(llm=mock_llm)
    state = _make_state(
        investment_objective="balanced",
        investment_horizon="medium_term",
        risk_tolerance="moderate",
        report_markdown=_WELL_ALIGNED_REPORT,
    )

    result = scorer.step(state)

    # Verify the StepResult contains the score under the correct key
    assert "input_context_appropriateness_score" in result.state_update
    score_obj = result.state_update["input_context_appropriateness_score"]
    assert score_obj.dimension == "input_context_appropriateness"
    # well-aligned → mock returns 9.0 → ≥ 8.5 (normalized ≥ 0.85)
    assert score_obj.score >= 8.5, f"Expected score ≥ 8.5, got {score_obj.score}"
    assert score_obj.evidence  # evidence must be non-empty


@pytest.mark.usefixtures("_force_llm_mode_mock")
def test_scorer_low_score_for_generic_boilerplate(monkeypatch: pytest.MonkeyPatch) -> None:
    """generic boilerplate 报告:内容与 6 字段无关 → mock LLM 返回低分 → score ≤ 5.0。

    The scorer passes the 6 input fields to the LLM judge. For a generic report
    that doesn't reference the input fields, the real judge should give a low score.
    This test mocks the LLM to return score=3.0, verifying score parsing.
    """
    monkeypatch.setenv("LLM_MODE", "mock")

    low_score_response = '{"score": 3.0, "evidence": "报告未提及 balanced 目标或 moderate 风险;仓位 5% 建议与风险承受度无关联说明;报告内容为通用茅台介绍,无客户特化内容。"}'
    mock_llm = _make_mock_llm(low_score_response)

    scorer = InputContextAppropriatenessScorer(llm=mock_llm)
    state = _make_state(
        investment_objective="capital_preservation",
        investment_horizon="long_term",
        risk_tolerance="conservative",
        report_markdown=_GENERIC_BOILERPLATE_REPORT,
    )

    result = scorer.step(state)

    assert "input_context_appropriateness_score" in result.state_update
    score_obj = result.state_update["input_context_appropriateness_score"]
    assert score_obj.dimension == "input_context_appropriateness"
    # generic boilerplate → mock returns 3.0 → ≤ 5.0
    assert score_obj.score <= 5.0, f"Expected score ≤ 5.0, got {score_obj.score}"
    assert score_obj.evidence  # evidence must be non-empty


@pytest.mark.usefixtures("_force_llm_mode_mock")
def test_scorer_prompt_includes_6_input_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """scorer 的 judge prompt 必须包含全部 6 个输入字段的具体值。

    This is the key behavioral test: verifying that InputContextAppropriatenessScorer
    injects the 6 input fields into the prompt sent to the LLM, unlike the base
    _BaseScorer which only sends report_markdown + context.
    """
    monkeypatch.setenv("LLM_MODE", "mock")

    captured_prompts: list[str] = []

    mock_llm = MagicMock()
    mock_response = LLMResponse(
        content='{"score": 7.0, "evidence": "中等分数"}',
        parsed=None,
        model="qwen-turbo",
        tier="fast",
        prompt_tokens=300,
        completion_tokens=30,
        total_tokens=330,
        cost_cny=0.001,
        latency_ms=50,
        request_id="req-mock-002",
    )

    def capture_chat(**kwargs: object) -> LLMResponse:
        prompt_val = kwargs.get("prompt", "")
        if isinstance(prompt_val, str):
            captured_prompts.append(prompt_val)
        return mock_response

    mock_llm.chat.side_effect = capture_chat

    scorer = InputContextAppropriatenessScorer(llm=mock_llm)
    state = _make_state(
        investment_objective="aggressive_growth",
        investment_horizon="short_term",
        risk_tolerance="very_aggressive",
        client_total_aum=5_000_000.0,
        target_ts_code="600519.SH",
        report_markdown="茅台研报内容...",
    )

    scorer.step(state)

    assert captured_prompts, "LLM chat was never called"
    prompt = captured_prompts[0]

    # All 6 input fields must appear in the judge prompt
    assert "aggressive_growth" in prompt, "investment_objective not in prompt"
    assert "short_term" in prompt, "investment_horizon not in prompt"
    assert "very_aggressive" in prompt, "risk_tolerance not in prompt"
    assert "5,000,000" in prompt, "client_total_aum not in prompt"
    assert "600519.SH" in prompt, "target_ts_code not in prompt"
    # report content must also be injected
    assert "茅台研报内容" in prompt, "report_markdown not in prompt"


@pytest.mark.usefixtures("_force_llm_mode_mock")
def test_scorer_span_metadata_has_dimension(monkeypatch: pytest.MonkeyPatch) -> None:
    """StepResult.span_metadata 必须含 dimension = 'input_context_appropriateness'。"""
    monkeypatch.setenv("LLM_MODE", "mock")

    mock_llm = _make_mock_llm('{"score": 7.5, "evidence": "测试证据"}')
    scorer = InputContextAppropriatenessScorer(llm=mock_llm)
    state = _make_state()

    result = scorer.step(state)

    assert result.span_metadata["dimension"] == "input_context_appropriateness"
    assert result.span_metadata["agent"] == "InputContextAppropriatenessScorer"


# ---------------------------------------------------------------------------
# Autouse fixture for LLM_MODE guard
# ---------------------------------------------------------------------------


@pytest.fixture
def _force_llm_mode_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force LLM_MODE=mock so LLMService.__init__ doesn't raise RuntimeError.

    Note: we inject a MagicMock as llm directly, so LLMService is never
    actually constructed — but the env var must be != 'none' for the guard.
    This fixture is a safety net for any imports that check LLM_MODE.
    """
    monkeypatch.setenv("LLM_MODE", "mock")
