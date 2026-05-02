"""L0 — LLMResponse schema roundtrip and required-field invariants."""

import pytest
from app.services.llm_response import LLMResponse
from pydantic import ValidationError


def test_minimal_response_validates() -> None:
    r = LLMResponse(
        content="hello",
        model="deepseek-v3.2",
        tier="fast",
        prompt_tokens=10,
        completion_tokens=2,
        total_tokens=12,
        cost_cny=0.0001,
        latency_ms=320,
    )
    assert r.content == "hello"
    assert r.cache_hit is False  # default


def test_negative_tokens_rejected() -> None:
    with pytest.raises(ValidationError):
        LLMResponse(
            content="x",
            model="m",
            tier="fast",
            prompt_tokens=-1,
            completion_tokens=0,
            total_tokens=0,
            cost_cny=0.0,
            latency_ms=0,
        )


def test_invalid_tier_rejected() -> None:
    with pytest.raises(ValidationError):
        LLMResponse(
            content="x",
            model="m",
            tier="ultra",  # type: ignore[arg-type]
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            cost_cny=0.0,
            latency_ms=0,
        )


def test_roundtrip_json() -> None:
    r = LLMResponse(
        content="hi",
        model="m",
        tier="balanced",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        cost_cny=0.0,
        latency_ms=1,
        cache_hit=True,
    )
    assert LLMResponse.model_validate_json(r.model_dump_json()) == r


def test_inconsistent_total_tokens_rejected() -> None:
    with pytest.raises(ValidationError):
        LLMResponse(
            content="x",
            model="m",
            tier="fast",
            prompt_tokens=2,
            completion_tokens=3,
            total_tokens=99,
            cost_cny=0.0,
            latency_ms=0,
        )


def test_roundtrip_json_with_parsed_dict() -> None:
    r = LLMResponse(
        content="ok",
        model="m",
        tier="deep",
        prompt_tokens=5,
        completion_tokens=3,
        total_tokens=8,
        cost_cny=0.0,
        latency_ms=10,
        parsed={"score": 8, "reason": "ok", "nested": {"k": 1}},
    )
    assert LLMResponse.model_validate_json(r.model_dump_json()) == r
