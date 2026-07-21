"""Pure resolution of the model identity used by the production LLM factory."""

from __future__ import annotations

import os
from collections.abc import Mapping

from app.services.tier_router import V0_DEFAULT_MODEL


def resolve_llm_identity_from_env(
    environment: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """Return provider/model without constructing clients or database services."""
    values = os.environ if environment is None else environment
    return "dashscope", values.get("MOCK_TUSHARE_MODEL", V0_DEFAULT_MODEL)
