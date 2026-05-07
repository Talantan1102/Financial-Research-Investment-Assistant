"""Portfolio exceptions raise + message correctness tests."""

from __future__ import annotations

import pytest
from app.services.portfolio_exceptions import (
    ExpiredDeletionError,
    ImmutableTradeError,
    PortfolioError,
)


def test_immutable_trade_error_inherits_portfolio_error() -> None:
    err = ImmutableTradeError("常规交易不可改字段,过 24h 也不可")
    assert isinstance(err, PortfolioError)
    assert "不可改" in str(err)


def test_expired_deletion_error_inherits_portfolio_error() -> None:
    err = ExpiredDeletionError("超 24h 不可删,请录反向交易抵消")
    assert isinstance(err, PortfolioError)
    assert "24h" in str(err)


def test_can_catch_both_via_base_class() -> None:
    with pytest.raises(PortfolioError):
        raise ImmutableTradeError("x")
    with pytest.raises(PortfolioError):
        raise ExpiredDeletionError("y")
