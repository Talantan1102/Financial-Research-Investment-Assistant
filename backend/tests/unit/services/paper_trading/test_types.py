from datetime import datetime
from decimal import Decimal

import pytest
from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.types import QuoteLevel, RealtimeQuote
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


def test_error_exposes_stable_code() -> None:
    exc = PaperTradingError("stale_quote", "行情已过期")
    assert exc.code == "stale_quote"
    assert str(exc) == "行情已过期"
