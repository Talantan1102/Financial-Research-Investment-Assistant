"""L0 — Judge prompt assembly + response parsing.

L1 SUT-Judge integration is in test_eval_runner.py; this test isolates the
prompt-construction and JSON-parsing units.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from app.services.eval_models import GoldenCase, JudgeScores
from app.services.judge import Judge, build_judge_prompt
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService

FIXTURES = Path("backend/tests/fixtures/llm_mocks")


# ---------------------------------------------------------------------------
# Minimal stub ChatClient for C10 tests — returns a fixed content string
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _StubRaw:
    """Satisfies ChatCompletionRaw protocol."""

    content: str
    prompt_tokens: int = 10
    completion_tokens: int = 20


class _StubClient:
    """ChatClient stub — always returns the content it was constructed with."""

    def __init__(self, content: str) -> None:
        self._content = content

    def chat(self, prompt: str, model: str, schema: dict[str, Any] | None) -> _StubRaw:
        return _StubRaw(content=self._content)


def _make_case() -> GoldenCase:
    return GoldenCase(
        case_id="c10_test",
        category="single_tool_call",
        user_input="茅台股价?",
        expected_behavior={"response_must_contain": ["600519"]},
        metadata={"added_by": "test", "added_at": "2026-06-01", "tags": []},
    )


def test_build_judge_prompt_includes_required_sections() -> None:
    case = GoldenCase(
        case_id="x",
        category="single_tool_call",
        user_input="茅台股价?",
        expected_behavior={"response_must_contain": ["600519", "元"]},
        metadata={"added_by": "test", "added_at": "2026-04-30", "tags": []},
    )
    prompt = build_judge_prompt(
        case=case,
        sut_response="茅台 600519.SH 股价 1820 元/股。",
        trace_summary="LLMService.chat called 1x, no tool calls",
    )
    assert "你是金融研究助手的输出评审员" in prompt
    assert "茅台股价?" in prompt
    assert "600519" in prompt
    assert "factuality" in prompt
    assert "tool_correctness" in prompt
    assert "coverage" in prompt
    assert "structure" in prompt


def test_judge_returns_parsed_scores(
    monkeypatch: pytest.MonkeyPatch,
    mock_llm_client: MockLLMClient,
) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    svc = LLMService(client=mock_llm_client)
    j = Judge(llm=svc, judge_tier="balanced")
    case = GoldenCase(
        case_id="x",
        category="single_tool_call",
        user_input="茅台股价?",
        expected_behavior={"response_must_contain": ["600519", "元"]},
        metadata={"added_by": "test", "added_at": "2026-04-30", "tags": []},
    )

    scores, judge_meta = j.score(
        case=case,
        sut_response="茅台 600519.SH 股价 1820 元/股。",
        trace_summary="LLMService.chat called 1x, no tool calls",
    )

    assert isinstance(scores, JudgeScores)
    assert 0 <= scores.factuality <= 10
    assert scores.tool_correctness is None
    assert scores.coverage is not None
    assert judge_meta["model"]
    assert judge_meta["latency_ms"] >= 0


# ---------------------------------------------------------------------------
# C10 regression: JSON mode + descriptive error on non-JSON LLM output
# ---------------------------------------------------------------------------

_VALID_JUDGE_JSON = """{
  "factuality": {"score": 7, "evidence": "accurate"},
  "tool_correctness": {"score": null, "evidence": "N/A"},
  "coverage": {"score": 8, "evidence": "good coverage"},
  "structure": {"score": 9, "evidence": "well structured"}
}"""


def test_judge_score_passes_schema_to_chat_and_parses_valid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C10: Judge.score with clean JSON response parses into JudgeScores without error."""
    monkeypatch.setenv("LLM_MODE", "mock")
    svc = LLMService(client=_StubClient(content=_VALID_JUDGE_JSON))
    j = Judge(llm=svc, judge_tier="balanced")
    scores, meta = j.score(
        case=_make_case(),
        sut_response="茅台 600519.SH 1820 元",
        trace_summary="no tool calls",
    )
    assert isinstance(scores, JudgeScores)
    assert scores.factuality == 7
    assert scores.coverage == 8
    assert scores.tool_correctness is None  # null in JSON → None
    assert "model" in meta


def test_judge_score_raises_value_error_on_non_json_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C10: When LLM returns non-JSON, Judge.score raises ValueError (not bare
    JSONDecodeError) and includes the raw content in the message."""
    monkeypatch.setenv("LLM_MODE", "mock")
    bad_content = "not json at all"
    svc = LLMService(client=_StubClient(content=bad_content))
    j = Judge(llm=svc, judge_tier="balanced")
    with pytest.raises(ValueError, match="Judge LLM returned non-JSON"):
        j.score(
            case=_make_case(),
            sut_response="some response",
            trace_summary="no tool calls",
        )


def test_judge_score_raises_value_error_on_fenced_json_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C10: Markdown-fenced JSON (the output without JSON mode) also raises ValueError
    with the raw content, confirming schema={type:object} is needed to avoid fences."""
    monkeypatch.setenv("LLM_MODE", "mock")
    fenced = "```json\n" + _VALID_JUDGE_JSON + "\n```"
    svc = LLMService(client=_StubClient(content=fenced))
    j = Judge(llm=svc, judge_tier="balanced")
    with pytest.raises(ValueError, match="Judge LLM returned non-JSON"):
        j.score(
            case=_make_case(),
            sut_response="some response",
            trace_summary="no tool calls",
        )


def test_judge_score_raises_value_error_on_missing_required_dim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C10: When required JSON key is missing, raises ValueError with dimension name."""
    monkeypatch.setenv("LLM_MODE", "mock")
    # omit 'structure' dimension entirely
    incomplete_json = """{
      "factuality": {"score": 7, "evidence": "ok"},
      "tool_correctness": {"score": null, "evidence": "N/A"},
      "coverage": {"score": 8, "evidence": "ok"}
    }"""
    svc = LLMService(client=_StubClient(content=incomplete_json))
    j = Judge(llm=svc, judge_tier="balanced")
    with pytest.raises(ValueError, match="structure"):
        j.score(
            case=_make_case(),
            sut_response="some response",
            trace_summary="no tool calls",
        )
