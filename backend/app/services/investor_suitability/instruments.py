"""Deterministic, fail-closed A-share market classification."""

from __future__ import annotations

from app.models.investor_suitability import Market
from app.services.paper_trading.errors import PaperTradingError


def classify_market(ts_code: str) -> Market:
    """Return the permission market for a supported A-share common stock."""
    if not isinstance(ts_code, str):
        raise _unsupported_market()
    code, separator, exchange = ts_code.upper().partition(".")
    if separator != "." or len(code) != 6 or not code.isascii() or not code.isdecimal():
        raise _unsupported_market()
    if exchange == "SH" and code.startswith("688"):
        return Market.STAR
    if exchange == "SZ" and code.startswith(("300", "301")):
        return Market.CHINEXT
    if exchange == "BJ":
        return Market.BSE
    if (exchange == "SH" and code.startswith(("600", "601", "603", "605"))) or (
        exchange == "SZ" and code.startswith(("000", "001", "002", "003"))
    ):
        return Market.MAIN
    raise _unsupported_market()


def _unsupported_market() -> PaperTradingError:
    return PaperTradingError("unsupported_instrument_market", "无法识别证券所属交易市场")
