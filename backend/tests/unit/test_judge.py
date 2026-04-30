"""L0 — Judge prompt assembly + response parsing.

L1 SUT-Judge integration is in test_eval_runner.py; this test isolates the
prompt-construction and JSON-parsing units.
"""

from pathlib import Path

import pytest
from app.services.eval_models import GoldenCase, JudgeScores
from app.services.judge import Judge, build_judge_prompt
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService

FIXTURES = Path("backend/tests/fixtures/llm_mocks")


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
