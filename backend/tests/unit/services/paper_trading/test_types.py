from datetime import date, datetime
from decimal import Decimal

import pytest
from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.types import (
    FeeBreakdown,
    QuoteLevel,
    RealtimeQuote,
    RuleSet,
)
from pydantic import ValidationError


def _quote_levels(count: int = 5) -> tuple[QuoteLevel, ...]:
    return tuple(
        QuoteLevel(price=Decimal("1501.00") - index, quantity=100 * (index + 1))
        for index in range(count)
    )


def _valid_quote_data() -> dict[str, object]:
    return {
        "ts_code": "600519.SH",
        "name": "贵州茅台",
        "quoted_at": datetime(2026, 7, 20, 10, 0),
        "previous_close": Decimal("1500.00"),
        "last_price": Decimal("1501.00"),
        "bids": _quote_levels(),
        "asks": _quote_levels(),
        "source": "fixture",
        "suspended": False,
    }


def test_quote_accepts_decimal_values_and_exactly_five_levels() -> None:
    quote = RealtimeQuote.model_validate(_valid_quote_data())

    assert quote.previous_close == Decimal("1500.00")
    assert len(quote.bids) == 5
    assert len(quote.asks) == 5


def test_quote_rejects_float_decimal_field() -> None:
    data = _valid_quote_data()
    data["previous_close"] = 1500.0

    with pytest.raises(ValidationError):
        RealtimeQuote.model_validate(data)


@pytest.mark.parametrize("side", ["bids", "asks"])
def test_quote_requires_exactly_five_levels(side: str) -> None:
    data = _valid_quote_data()
    data[side] = _quote_levels(4)

    with pytest.raises(ValidationError, match="exactly five quote levels required"):
        RealtimeQuote.model_validate(data)


def _valid_rule_set_data() -> dict[str, object]:
    return {
        "version": "2026.07",
        "effective_from": date(2026, 7, 20),
        "board": "main",
        "risk_warning": False,
        "side": "buy",
        "buy_lot_size": 100,
        "price_tick": Decimal("0.01"),
        "price_limit_ratio": Decimal("0.10"),
        "quote_freshness_seconds": 3,
    }


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("buy_lot_size", 0),
        ("price_tick", Decimal("0")),
        ("price_limit_ratio", Decimal("0")),
        ("quote_freshness_seconds", 0),
    ],
)
def test_rule_set_rejects_nonpositive_values(
    field: str, invalid_value: object
) -> None:
    data = _valid_rule_set_data()
    data[field] = invalid_value

    with pytest.raises(ValidationError):
        RuleSet.model_validate(data)


@pytest.mark.parametrize("component", ["commission", "stamp_duty", "transfer_fee"])
def test_fee_breakdown_rejects_negative_component(component: str) -> None:
    data = {
        "commission": Decimal("5.00"),
        "stamp_duty": Decimal("1.50"),
        "transfer_fee": Decimal("0.25"),
    }
    data[component] = Decimal("-0.01")

    with pytest.raises(ValidationError):
        FeeBreakdown.model_validate(data)


def test_fee_breakdown_total_is_exact_decimal_sum() -> None:
    fee = FeeBreakdown(
        commission=Decimal("5.00"),
        stamp_duty=Decimal("1.50"),
        transfer_fee=Decimal("0.25"),
    )

    assert fee.total == Decimal("6.75")


def test_fee_breakdown_rejects_assignment() -> None:
    fee = FeeBreakdown(
        commission=Decimal("5.00"),
        stamp_duty=Decimal("1.50"),
        transfer_fee=Decimal("0.25"),
    )

    with pytest.raises(ValidationError, match="Instance is frozen"):
        fee.commission = Decimal("0")


def test_error_exposes_stable_code() -> None:
    exc = PaperTradingError("stale_quote", "行情已过期")
    assert exc.code == "stale_quote"
    assert str(exc) == "行情已过期"
