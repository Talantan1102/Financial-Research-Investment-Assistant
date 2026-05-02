"""Pricing table — per-model CNY-per-1K-token rates + cost computation.

Pure data + pure function. No I/O, no Pydantic. Reasoning-model pricing:
DashScope bills reasoning_tokens as part of completion_tokens, so callers
that pass `completion_tokens` from the OpenAI usage block are already
accounting for reasoning. compute_cost takes plain prompt/completion ints.

Sources:
- DashScope deepseek-v4-flash: ¥0.0002 / 1K input, ¥0.0008 / 1K output
  (as of 2026-04). Account decommissioned 2026-05-03; entry retained for
  legacy cassette / unit-test fixtures.
- token-plan deepseek-v3.2: ¥0.0005 / 1K input, ¥0.002 / 1K output
  (token-plan prepaid bundle, effective rate as of 2026-05-03; update
  when the bundle is renegotiated).
"""

from __future__ import annotations

from dataclasses import dataclass

# Public price constants — referenced from tests
DEEPSEEK_V4_FLASH_INPUT_CNY_PER_1K: float = 0.0002
DEEPSEEK_V4_FLASH_OUTPUT_CNY_PER_1K: float = 0.0008
DEEPSEEK_V32_INPUT_CNY_PER_1K: float = 0.0005
DEEPSEEK_V32_OUTPUT_CNY_PER_1K: float = 0.002


@dataclass(frozen=True)
class ModelPrice:
    input_per_1k_cny: float
    output_per_1k_cny: float


_TABLE: dict[str, ModelPrice] = {
    "deepseek-v4-flash": ModelPrice(
        input_per_1k_cny=DEEPSEEK_V4_FLASH_INPUT_CNY_PER_1K,
        output_per_1k_cny=DEEPSEEK_V4_FLASH_OUTPUT_CNY_PER_1K,
    ),
    "deepseek-v3.2": ModelPrice(
        input_per_1k_cny=DEEPSEEK_V32_INPUT_CNY_PER_1K,
        output_per_1k_cny=DEEPSEEK_V32_OUTPUT_CNY_PER_1K,
    ),
}


class PriceUnknownModelError(KeyError):
    """Raised when get_price is called with a model not in the price table."""


def get_price(model: str) -> ModelPrice:
    if model not in _TABLE:
        raise PriceUnknownModelError(
            f"no price entry for model={model!r}; add it to pricing._TABLE"
        )
    return _TABLE[model]


def compute_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    p = get_price(model)
    return (
        prompt_tokens * p.input_per_1k_cny / 1000 + completion_tokens * p.output_per_1k_cny / 1000
    )
