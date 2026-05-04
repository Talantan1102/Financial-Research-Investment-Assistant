"""Unit tests for ResearchRequest 6 structured fields (v0.8.4)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_research_request_accepts_6_structured_fields() -> None:
    from app.agents.schemas import (
        ResearchRequest,
    )  # noqa: F401

    req = ResearchRequest(
        target_ts_code="600519.SH",
        client_total_aum=10_000_000.0,
        client_existing_position=500_000.0,
        investment_objective="balanced",
        investment_horizon="medium_term",
        risk_tolerance="moderate",
        user_message=None,
    )
    assert req.target_ts_code == "600519.SH"
    assert req.investment_objective == "balanced"


def test_research_request_validates_enum() -> None:
    from app.agents.schemas import ResearchRequest

    with pytest.raises(ValidationError):
        ResearchRequest(
            target_ts_code="600519.SH",
            client_total_aum=10_000_000.0,
            investment_objective="invalid_value",  # type: ignore[arg-type]
            investment_horizon="medium_term",
            risk_tolerance="moderate",
        )
