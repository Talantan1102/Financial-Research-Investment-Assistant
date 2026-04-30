"""TierRouter — resolves a logical tier to a concrete model name.

v0 maps all tiers to deepseek-v4-flash (spec § 7). The interface stays
stable so v1+ can swap to multi-model with a config change only.
"""

from pydantic import BaseModel, ConfigDict

from app.services.llm_response import Tier

V0_DEFAULT_MODEL = "deepseek-v4-flash"


class TierConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    fast: str
    balanced: str
    deep: str


class TierRouter:
    def __init__(self, config: TierConfig) -> None:
        self._config = config

    @classmethod
    def from_default_v0_config(cls) -> "TierRouter":
        return cls(
            TierConfig(
                fast=V0_DEFAULT_MODEL,
                balanced=V0_DEFAULT_MODEL,
                deep=V0_DEFAULT_MODEL,
            )
        )

    def resolve(self, tier: Tier) -> str:
        match tier:
            case "fast":
                return self._config.fast
            case "balanced":
                return self._config.balanced
            case "deep":
                return self._config.deep
            case _:
                raise ValueError(f"unknown tier: {tier!r}")
