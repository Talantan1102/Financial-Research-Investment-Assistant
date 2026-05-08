"""Pydantic schema validation tests for portfolio endpoints."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from app.schemas.portfolio import (
    OnboardingRequest,
    PositionRead,
    TradeCreate,
    TradeUpdate,
)
from pydantic import ValidationError


def test_trade_create_accepts_valid_initial() -> None:
    payload = {
        "ts_code": "600519.SH",
        "name": "贵州茅台",
        "type": "initial",
        "quantity": 200,
        "price": "1450.00",
        "trade_date": "2024-06-01",
        "note": "looks good",
    }
    tc = TradeCreate(**payload)  # type: ignore[arg-type]
    assert tc.type == "initial"
    assert tc.quantity == 200
    assert tc.price == Decimal("1450.00")


def test_trade_create_rejects_negative_quantity() -> None:
    with pytest.raises(ValidationError):
        TradeCreate(
            ts_code="600519.SH",
            name="贵州茅台",
            type="initial",
            quantity=-5,
            price=Decimal("1450.00"),
            trade_date=date(2024, 6, 1),
        )


def test_trade_create_rejects_zero_price() -> None:
    with pytest.raises(ValidationError):
        TradeCreate(
            ts_code="600519.SH",
            name="贵州茅台",
            type="initial",
            quantity=10,
            price=Decimal("0"),
            trade_date=date(2024, 6, 1),
        )


def test_trade_update_only_accepts_initial_updatable_fields() -> None:
    """update 仅允许 ts_code / name / quantity / price / trade_date / note;type 不可改。"""
    valid = TradeUpdate(price=Decimal("1455.00"))
    assert valid.price == Decimal("1455.00")

    with pytest.raises(ValidationError):
        TradeUpdate(type="buy")  # type: ignore[call-arg]  # type 不在 schema fields 中


def test_position_read_serializes_quote_fields() -> None:
    pr = PositionRead(
        id="abc",
        ts_code="600519.SH",
        name="贵州茅台",
        quantity=220,
        avg_cost=Decimal("1460.00"),
        total_cost=Decimal("321200.00"),
        realized_pnl=Decimal("4200.00"),
        last_quote_price=Decimal("1580.00"),
        last_quote_at=None,
        is_silenced=False,
    )
    assert pr.quantity == 220


def test_onboarding_request_validates_at_least_one_initial() -> None:
    with pytest.raises(ValidationError):
        OnboardingRequest(trades=[])
