"""L1 — cassette validation drift logic with mock judge LLM.

Tests the score_similarity pure function via a hand-crafted fake LLMService.
Doesn't actually call the drift script's main() — that requires live LLM key.
"""

import json
from typing import Any

import pytest
import yaml
from app.services.llm_service import LLMService

from tests.eval import cassette_validation as cv


class _FakeChat:
    """Returns a fixed text on every chat() — for testing digit-extraction."""

    def __init__(self, text: str) -> None:
        self._text = text

    def chat(self, prompt: str, model: str, schema: dict[str, Any] | None) -> Any:
        class _R:
            content = self._text
            prompt_tokens = 1
            completion_tokens = 1

        return _R()


def _make_svc(text: str) -> LLMService:
    return LLMService(client=_FakeChat(text))


def test_score_similarity_extracts_int() -> None:
    svc = _make_svc("8")
    sim = cv.score_similarity(svc, old="x", new="y")
    assert sim == 8


def test_score_similarity_clamps_above_10() -> None:
    """Two-digit values get clamped: '12' → first 2 digits → 12 → clamp to 10."""
    svc = _make_svc("12 (out of range)")
    sim = cv.score_similarity(svc, old="x", new="y")
    assert sim == 10


def test_score_similarity_no_digits_returns_zero() -> None:
    svc = _make_svc("not a number")
    sim = cv.score_similarity(svc, old="x", new="y")
    assert sim == 0


def test_score_similarity_extracts_first_two_digits() -> None:
    """Verifies digit extraction logic: 'score: 7/10' → digits '710' → first 2 '71' → clamp to 10.

    This is a known characteristic of the simplified digit-extraction; the
    judge prompt explicitly asks for a single integer 0-10, so multi-digit
    junk responses are pathological. The clamp ensures we never return
    nonsense like 71.
    """
    svc = _make_svc("score: 7/10")
    sim = cv.score_similarity(svc, old="x", new="y")
    assert sim == 10


def test_score_similarity_zero() -> None:
    svc = _make_svc("0")
    sim = cv.score_similarity(svc, old="x", new="y")
    assert sim == 0


@pytest.mark.parametrize(
    "sims,expected",
    [
        ([9], "OK"),  # first sample passes, no resample
        ([8], "OK"),  # exactly at threshold counts as OK
        ([5, 9, 10], "OK"),  # one-off low out-voted by two highs (the false-positive case)
        ([7, 7, 9], "DRIFT"),  # strict majority (2 of 3) below threshold
        ([4, 5, 3], "DRIFT"),  # genuine drift: every sample low
        ([5, 4], "DRIFT"),  # two independent lows = drift
        ([5, 9], "OK"),  # 1 low + 1 high → no majority → OK
        ([5], "UNCONFIRMED"),  # lone low, resamples unavailable → infra-skip, not drift
    ],
)
def test_classify_drift_verdict(sims: list[int], expected: str) -> None:
    """Resample-majority verdict — encodes the truth table the drift fix relies on."""
    assert cv._classify_drift(sims) == expected


# ---------------------------------------------------------------------------
# _extract_first_interaction skip paths — one bad cassette must not crash the
# nightly sweep (2026-06 root cause: chat-loop SSE streaming cassettes made
# json.loads blow up and the whole drift job exit 1 before finishing).
# ---------------------------------------------------------------------------


def _write_cassette(tmp_path: Any, response_body: Any) -> Any:
    data = {
        "interactions": [
            {
                "request": {
                    "body": json.dumps(
                        {"model": "m", "messages": [{"role": "user", "content": "你好"}]}
                    )
                },
                "response": {"body": {"string": response_body}},
            }
        ]
    }
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


def test_extract_skips_sse_streaming_cassette(tmp_path: Any) -> None:
    """chat-loop streaming cassettes (SSE `data:` chunks) are skipped, not crashed on."""
    sse = 'data: {"choices":[{"delta":{"content":null,"role":"assistant"}}]}\n\ndata: [DONE]\n'
    assert cv._extract_first_interaction(_write_cassette(tmp_path, sse)) is None


def test_extract_skips_non_json_body(tmp_path: Any) -> None:
    assert cv._extract_first_interaction(_write_cassette(tmp_path, "<html>oops</html>")) is None


def test_extract_skips_empty_content(tmp_path: Any) -> None:
    """Tool-call-only responses (content null/empty) carry no text to drift-compare."""
    body = json.dumps({"choices": [{"message": {"content": None, "tool_calls": []}}]})
    assert cv._extract_first_interaction(_write_cassette(tmp_path, body)) is None


def test_extract_returns_plain_text_response(tmp_path: Any) -> None:
    body = json.dumps({"choices": [{"message": {"content": "茅台行情如下"}}]})
    ext = cv._extract_first_interaction(_write_cassette(tmp_path, body))
    assert ext is not None
    model, prompt, recorded = ext
    assert (model, prompt, recorded) == ("m", "你好", "茅台行情如下")
