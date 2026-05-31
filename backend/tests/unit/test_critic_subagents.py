"""L0 — 5 Critic sub-agents prompt construction + score parsing."""

import pytest
from app.agents.critic_subagents._base_scorer import _parse_score
from app.agents.critic_subagents.conciseness import ConcisenessScorer
from app.agents.critic_subagents.coverage import CoverageScorer
from app.agents.critic_subagents.factuality import FactualityScorer
from app.agents.critic_subagents.insight import InsightScorer
from app.agents.critic_subagents.structure import StructureScorer
from app.agents.schemas import (
    CriticDimensionScore,
    Insight,
    ResearchPlan,
    ResearchState,
    Subtask,
)
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService


def _state_with_report() -> ResearchState:
    return ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="req-test1234",
        report_markdown="# 茅台研报\n\n股价 1820.5。",
        insights=[
            Insight(subtask_id="overview", finding="x", supporting_data=[], confidence="high")
        ],
        plan=ResearchPlan(
            rationale="default test plan",
            subtasks=[
                Subtask(subtask_id="overview", description="d", required_tools=[], rationale="r")
            ],
        ),
    )


@pytest.mark.parametrize(
    "ScorerCls,dim",
    [
        (FactualityScorer, "factuality"),
        (CoverageScorer, "coverage"),
        (InsightScorer, "insight"),
        (StructureScorer, "structure"),
        (ConcisenessScorer, "conciseness"),
    ],
)
def test_scorer_returns_dimension_score(
    ScorerCls: type, dim: str, mock_llm_client: MockLLMClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    svc = LLMService(client=mock_llm_client)
    scorer = ScorerCls(llm=svc)

    state = _state_with_report()
    sr = scorer.step(state)

    score = sr.state_update[f"{dim}_score"]
    assert isinstance(score, CriticDimensionScore)
    assert score.dimension == dim
    in_range = 0.0 <= score.score <= 10.0
    assert in_range


# ── C22: _parse_score error handling ─────────────────────────────────────────


def test_parse_score_valid_json_returns_score() -> None:
    """C22: well-formed JSON round-trips correctly."""
    result = _parse_score(
        '{"score": 8, "evidence": "ok"}',
        dimension="factuality",
        request_id="req-test",
    )
    assert isinstance(result, CriticDimensionScore)
    assert result.score == pytest.approx(8.0)
    assert result.evidence == "ok"


def test_parse_score_valid_json_in_fence() -> None:
    """C22: markdown code fence is stripped before parsing."""
    result = _parse_score(
        '```json\n{"score": 7, "evidence": "fence"}\n```',
        dimension="coverage",
        request_id="req-fence",
    )
    assert result.score == pytest.approx(7.0)


def test_parse_score_truncated_json_raises_value_error() -> None:
    """C22: truncated JSON (e.g. reasoning model cut off) raises ValueError with context."""
    with pytest.raises(ValueError, match="_parse_score failed") as exc_info:
        _parse_score(
            '{"score": 8',  # truncated — JSONDecodeError
            dimension="factuality",
            request_id="req-trunc",
        )
    msg = str(exc_info.value)
    assert "factuality" in msg
    assert "req-trunc" in msg


def test_parse_score_missing_score_key_raises_value_error() -> None:
    """C22: JSON without 'score' key raises ValueError with context."""
    with pytest.raises(ValueError, match="_parse_score failed") as exc_info:
        _parse_score(
            '{"evidence": "ok"}',  # missing 'score' key — KeyError
            dimension="coverage",
            request_id="req-nokey",
        )
    msg = str(exc_info.value)
    assert "coverage" in msg
    assert "req-nokey" in msg


def test_parse_score_non_json_raises_value_error() -> None:
    """C22: plain-text non-JSON output raises ValueError, not bare JSONDecodeError."""
    with pytest.raises(ValueError, match="_parse_score failed"):
        _parse_score(
            "not json at all",
            dimension="insight",
            request_id="req-nonjson",
        )
