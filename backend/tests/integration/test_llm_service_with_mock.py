"""L1 — LLMService end-to-end with MockLLMClient injected.

This is the canonical demo: a real LLMService instance (not stubbed) plus a
mock client. Asserts on output shape + tier resolution + latency_ms presence.
"""

import pytest
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService


def test_chat_fast_tier_returns_v0_default_model(
    mock_llm_client: MockLLMClient,
) -> None:
    svc = LLMService(client=mock_llm_client)
    r = svc.chat(prompt="What is the price of 600519.SH?", tier="fast")
    assert r.tier == "fast"
    assert r.model == "deepseek-v4-flash"
    assert "600519" in r.content
    assert r.latency_ms >= 0
    assert r.total_tokens == r.prompt_tokens + r.completion_tokens


def test_chat_with_pattern_match_returns_templated_content(
    mock_llm_client: MockLLMClient,
) -> None:
    svc = LLMService(client=mock_llm_client)
    r = svc.chat(prompt="Please get the quote for 000001.SZ", tier="balanced")
    assert "000001" in r.content
    assert r.tier == "balanced"


def test_chat_unknown_prompt_propagates_mock_miss(
    mock_llm_client: MockLLMClient,
) -> None:
    """LLMService doesn't swallow MockMissError — bubbles up so test sees a
    real failure when the fixture is incomplete."""
    from app.services.llm_mock_client import MockMissError

    svc = LLMService(client=mock_llm_client)
    with pytest.raises(MockMissError):
        svc.chat(prompt="totally unseen prompt", tier="fast")
