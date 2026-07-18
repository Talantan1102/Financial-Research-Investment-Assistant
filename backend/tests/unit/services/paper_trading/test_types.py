from datetime import datetime
from decimal import Decimal

import pytest
from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.types import RealtimeQuote
from pydantic import ValidationError


def test_quote_rejects_float_and_requires_five_levels() -> None:
    with pytest.raises(ValidationError):
        RealtimeQuote(
            ts_code="600519.SH",
            name="贵州茅台",
            quoted_at=datetime(2026, 7, 20, 10, 0),
            previous_close=1500.0,
            last_price=Decimal("1501.00"),
            bids=[],
            asks=[],
            source="fixture",
            suspended=False,
        )


def test_error_exposes_stable_code() -> None:
    exc = PaperTradingError("stale_quote", "行情已过期")
    assert exc.code == "stale_quote"
    assert str(exc) == "行情已过期"
