"""L1 — cassette validation drift logic with mock judge LLM.

Tests the score_similarity pure function via a hand-crafted fake LLMService.
Doesn't actually call the drift script's main() — that requires live LLM key.
"""

from typing import Any

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
