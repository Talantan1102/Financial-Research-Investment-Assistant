"""LLMResponse — the unified return shape from any LLMService.chat call.

Stable across v0~v3 per spec § 7. Adding fields is fine; renaming/removing
breaks all downstream consumers (tools, eval runner, trace exporter).
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Tier = Literal["fast", "balanced", "deep"]


class LLMResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str
    parsed: dict[str, Any] | None = None
    model: str
    tier: Tier
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    cost_cny: float = Field(ge=0.0)
    latency_ms: int = Field(ge=0)
    cache_hit: bool = False
