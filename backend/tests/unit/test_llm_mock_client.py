"""L0 — MockLLMClient 3-tier dispatch + fail-loud on miss."""

from pathlib import Path

import pytest
from app.services.llm_mock_client import MockLLMClient, MockMissError

FIXTURES = Path("backend/tests/fixtures/llm_mocks")


def test_static_dict_hit() -> None:
    client = MockLLMClient.from_fixture_dir(FIXTURES)
    r = client.chat(prompt="What is the price of 600519.SH?", model="m", schema=None)
    assert "600519" in r.content


def test_pattern_fallback_hit() -> None:
    """A prompt not in the static dict but matching a known regex falls back."""
    client = MockLLMClient.from_fixture_dir(FIXTURES)
    r = client.chat(prompt="Please get the quote for 000001.SZ", model="m", schema=None)
    # pattern entries return a templated string with the captured ticker
    assert "000001" in r.content


def test_recorded_fixture_hit() -> None:
    client = MockLLMClient.from_fixture_dir(FIXTURES)
    r = client.chat(
        prompt="__recorded__:sample_critic",  # explicit recorded-fixture pointer
        model="m",
        schema=None,
    )
    assert r.content.startswith("{")  # recorded fixture is a JSON blob


def test_total_miss_raises() -> None:
    client = MockLLMClient.from_fixture_dir(FIXTURES)
    with pytest.raises(MockMissError, match="no static / pattern / recorded match"):
        client.chat(prompt="something nobody put in the fixtures", model="m", schema=None)


def test_token_counts_are_deterministic() -> None:
    """Same prompt → same token counts. Critical for L1 flake control."""
    client = MockLLMClient.from_fixture_dir(FIXTURES)
    r1 = client.chat(prompt="What is the price of 600519.SH?", model="m", schema=None)
    r2 = client.chat(prompt="What is the price of 600519.SH?", model="m", schema=None)
    assert r1.prompt_tokens == r2.prompt_tokens
    assert r1.completion_tokens == r2.completion_tokens


def test_pattern_match_with_recorded_redirect() -> None:
    """A pattern entry whose response is `__recorded__:<id>` resolves
    via the recorded-fixture index."""
    client = MockLLMClient.from_fixture_dir(FIXTURES)
    r = client.chat(
        prompt="你是金融研究助手的输出评审员。请给一个示例。",
        model="m",
        schema=None,
    )
    # Recorded judge_4dim_response content is JSON; first chars are `{` or whitespace
    assert "factuality" in r.content
    assert "tool_correctness" in r.content
