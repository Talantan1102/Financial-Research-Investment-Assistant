"""L0 — Critic.dispatch_subagent real implementation + aggregate."""

from pathlib import Path
from typing import cast

import pytest
from app.agents.base import Agent
from app.agents.critic import Critic, aggregate_scores
from app.agents.critic_subagents.conciseness import ConcisenessScorer
from app.agents.critic_subagents.coverage import CoverageScorer
from app.agents.critic_subagents.factuality import FactualityScorer
from app.agents.critic_subagents.insight import InsightScorer
from app.agents.critic_subagents.structure import StructureScorer
from app.agents.schemas import (
    CriticDimension,
    CriticDimensionScore,
    CriticReport,
    ResearchState,
)
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService


def _state() -> ResearchState:
    return ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="req-test1234",
        report_markdown="# 测试研报",
    )


def test_critic_dispatch_subagent_real(
    mock_llm_client: MockLLMClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """v0.5: Critic.dispatch_subagent override v0 base.py 的 NotImplementedError 占位。"""
    monkeypatch.setenv("LLM_MODE", "mock")
    svc = LLMService(client=mock_llm_client)
    scorers: list[Agent] = [
        FactualityScorer(llm=svc),
        CoverageScorer(llm=svc),
        InsightScorer(llm=svc),
        StructureScorer(llm=svc),
        ConcisenessScorer(llm=svc),
    ]
    critic = Critic(llm=svc, scorers=scorers)

    sr = critic.dispatch_subagent(name="FactualityScorer", state=_state())
    assert "factuality_score" in sr.state_update


def test_critic_dispatch_subagent_unknown_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    fixture_dir = Path("backend/tests/fixtures/llm_mocks")
    svc = LLMService(client=MockLLMClient.from_fixture_dir(fixture_dir))
    critic = Critic(llm=svc, scorers=[])
    with pytest.raises(KeyError, match="not found"):
        critic.dispatch_subagent(name="NonExistent", state=_state())


def test_aggregate_scores_5_dims() -> None:
    dims = [
        CriticDimensionScore(
            dimension=cast(CriticDimension, d), score=8.0, evidence="e", sub_agent_request_id="r"
        )
        for d in ("factuality", "coverage", "insight", "structure", "conciseness")
    ]
    report = aggregate_scores(dims, summary="ok")
    assert isinstance(report, CriticReport)
    assert report.overall_score == 8.0


def test_critic_step_aggregates_5(
    mock_llm_client: MockLLMClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Critic.step provides sync fallback (not used by LangGraph subgraph)."""
    monkeypatch.setenv("LLM_MODE", "mock")
    svc = LLMService(client=mock_llm_client)
    scorers: list[Agent] = [
        FactualityScorer(llm=svc),
        CoverageScorer(llm=svc),
        InsightScorer(llm=svc),
        StructureScorer(llm=svc),
        ConcisenessScorer(llm=svc),
    ]
    critic = Critic(llm=svc, scorers=scorers)
    sr = critic.step(_state())
    report = sr.state_update["critic_report"]
    assert isinstance(report, CriticReport)
    n_dims = len(report.dimensions)
    assert n_dims == 5


# ── C18: aggregate_scores skip-sentinel filtering ────────────────────────────


def _make_dim(dim: str, score: float, *, is_skip: bool = False) -> CriticDimensionScore:
    """Build a CriticDimensionScore (C18: is_skip is now a real field on the model)."""
    return CriticDimensionScore(
        dimension=cast(CriticDimension, dim),
        score=score,
        evidence="skip" if is_skip else "e",
        sub_agent_request_id="r",
        is_skip=is_skip,
    )


def test_aggregate_scores_excludes_skip_dims() -> None:
    """C18: 6 real dims (6.0) + 2 skip dims (10.0) → overall_score == 6.0."""
    real_dims = [
        _make_dim(d, 6.0)
        for d in (
            "factuality",
            "coverage",
            "insight",
            "structure",
            "conciseness",
            "input_context_appropriateness",
        )
    ]
    skip_dims = [
        _make_dim("valuation_consistency", 10.0, is_skip=True),
        _make_dim("dialectical_balance", 10.0, is_skip=True),
    ]
    report = aggregate_scores(real_dims + skip_dims, summary="test")
    # All 8 dims must appear in the report
    assert len(report.dimensions) == 8
    # overall_score must exclude the 10.0 skip sentinels
    assert report.overall_score == pytest.approx(6.0)


def test_aggregate_scores_all_skip_yields_zero() -> None:
    """C18: when every dim is skipped, overall_score falls back to 0.0."""
    dims = [
        _make_dim(d, 10.0, is_skip=True) for d in ("valuation_consistency", "dialectical_balance")
    ]
    report = aggregate_scores(dims, summary="all skip")
    assert len(report.dimensions) == 2
    assert report.overall_score == pytest.approx(0.0)


def test_aggregate_scores_no_skip_unchanged() -> None:
    """C18: when no dims are skipped, behaviour is identical to pre-fix mean."""
    dims = [
        _make_dim(d, 8.0) for d in ("factuality", "coverage", "insight", "structure", "conciseness")
    ]
    report = aggregate_scores(dims, summary="ok")
    assert report.overall_score == pytest.approx(8.0)
