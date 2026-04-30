"""L0 — pricing table lookup + reasoning-tokens accounting."""

import pytest
from app.services.pricing import (
    DEEPSEEK_V4_FLASH_INPUT_CNY_PER_1K,
    DEEPSEEK_V4_FLASH_OUTPUT_CNY_PER_1K,
    PriceUnknownModelError,
    compute_cost,
    get_price,
)


def test_get_price_known_model() -> None:
    p = get_price("deepseek-v4-flash")
    assert p.input_per_1k_cny == DEEPSEEK_V4_FLASH_INPUT_CNY_PER_1K
    assert p.output_per_1k_cny == DEEPSEEK_V4_FLASH_OUTPUT_CNY_PER_1K


def test_get_price_unknown_model_raises() -> None:
    with pytest.raises(PriceUnknownModelError):
        get_price("gpt-99")


def test_compute_cost_simple() -> None:
    # 1000 input × ¥0.0002 = ¥0.0002; 500 output × ¥0.0008 = ¥0.0004; total ¥0.0006
    cost = compute_cost(model="deepseek-v4-flash", prompt_tokens=1000, completion_tokens=500)
    assert cost == pytest.approx(0.0006)


def test_compute_cost_reasoning_tokens_billed_as_output() -> None:
    """Per Plan C Task 0 spike: deepseek-v4-flash is a reasoning model;
    reasoning tokens are billed as output. The caller passes the total
    completion_tokens (which already includes reasoning). compute_cost
    does NOT need a separate reasoning_tokens param.
    """
    # 200 input + 549 completion (of which 400 is reasoning, all output-priced)
    cost = compute_cost(model="deepseek-v4-flash", prompt_tokens=200, completion_tokens=549)
    expected = (
        200 * DEEPSEEK_V4_FLASH_INPUT_CNY_PER_1K / 1000
        + 549 * DEEPSEEK_V4_FLASH_OUTPUT_CNY_PER_1K / 1000
    )
    assert cost == pytest.approx(expected)


def test_compute_cost_zero_tokens_zero_cost() -> None:
    assert compute_cost(model="deepseek-v4-flash", prompt_tokens=0, completion_tokens=0) == 0.0


def test_compute_cost_unknown_model_raises() -> None:
    with pytest.raises(PriceUnknownModelError):
        compute_cost(model="gpt-99", prompt_tokens=10, completion_tokens=5)
