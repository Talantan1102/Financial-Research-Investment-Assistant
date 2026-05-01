"""L0 — args-schema validation for the 3 v0 tools."""

import pytest
from app.tools.get_financials import FinancialsArgs
from app.tools.get_news import NewsArgs
from app.tools.get_stock_quote import StockQuoteArgs
from pydantic import ValidationError


def test_stock_quote_args_valid() -> None:
    args = StockQuoteArgs(ts_code="600519.SH")
    assert args.ts_code == "600519.SH"


def test_stock_quote_args_missing_code_rejected() -> None:
    with pytest.raises(ValidationError):
        StockQuoteArgs()  # type: ignore[call-arg]


def test_financials_args_valid_periods() -> None:
    for p in ("latest", "quarterly", "annual"):
        FinancialsArgs(ts_code="600519.SH", period=p)


def test_financials_args_invalid_period_rejected() -> None:
    with pytest.raises(ValidationError):
        FinancialsArgs(ts_code="600519.SH", period="weekly")  # type: ignore[arg-type]


def test_news_args_default() -> None:
    args = NewsArgs()
    assert args.ts_code is None
    assert args.n == 5
    assert args.days_back == 7


def test_news_args_negative_n_rejected() -> None:
    with pytest.raises(ValidationError):
        NewsArgs(n=-1)
