from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from app.models.paper_order import OrderSide, OrderType
from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.matcher import Execution, match_visible_depth
from app.services.paper_trading.types import QuoteLevel, RealtimeQuote
from pydantic import ValidationError

SHANGHAI = ZoneInfo("Asia/Shanghai")


def quote_fixture(
    *,
    bids: list[tuple[str, int]] | None = None,
    asks: list[tuple[str, int]] | None = None,
    suspended: bool = False,
) -> RealtimeQuote:
    bid_rows = bids or [
        ("9.99", 100),
        ("9.98", 200),
        ("9.97", 300),
        ("9.96", 400),
        ("9.95", 500),
    ]
    ask_rows = asks or [
        ("10.00", 100),
        ("10.01", 200),
        ("10.02", 300),
        ("10.03", 400),
        ("10.04", 500),
    ]
    return RealtimeQuote(
        ts_code="600519.SH",
        name="贵州茅台",
        quoted_at=datetime(2026, 7, 20, 10, tzinfo=SHANGHAI),
        previous_close=Decimal("9.80"),
        last_price=Decimal("9.99"),
        bids=tuple(
            QuoteLevel(price=Decimal(price), quantity=quantity) for price, quantity in bid_rows
        ),
        asks=tuple(
            QuoteLevel(price=Decimal(price), quantity=quantity) for price, quantity in ask_rows
        ),
        source="fixture",
        suspended=suspended,
    )


def pairs(executions: list[Execution]) -> list[tuple[Decimal, int]]:
    return [(execution.price, execution.quantity) for execution in executions]


def test_limit_buy_consumes_asks_best_first_and_partially_fills() -> None:
    quote = quote_fixture()

    executions = match_visible_depth(
        side="buy",
        order_type="limit",
        remaining=500,
        limit_price=Decimal("10.01"),
        quote=quote,
    )

    assert pairs(executions) == [(Decimal("10.00"), 100), (Decimal("10.01"), 200)]


def test_limit_sell_consumes_bids_best_first_and_stops_below_limit() -> None:
    executions = match_visible_depth(
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        remaining=500,
        limit_price=Decimal("9.98"),
        quote=quote_fixture(),
    )

    assert pairs(executions) == [(Decimal("9.99"), 100), (Decimal("9.98"), 200)]


@pytest.mark.parametrize("side", [OrderSide.BUY, OrderSide.SELL])
def test_market_order_consumes_all_visible_depth_until_remaining_is_filled(
    side: OrderSide,
) -> None:
    executions = match_visible_depth(
        side=side,
        order_type=OrderType.MARKET,
        remaining=450,
        limit_price=None,
        quote=quote_fixture(),
    )

    expected_prices = (
        ["10.00", "10.01", "10.02"] if side is OrderSide.BUY else ["9.99", "9.98", "9.97"]
    )
    assert pairs(executions) == [
        (Decimal(expected_prices[0]), 100),
        (Decimal(expected_prices[1]), 200),
        (Decimal(expected_prices[2]), 150),
    ]


def test_exact_fill_stops_without_touching_later_levels() -> None:
    executions = match_visible_depth(
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        remaining=300,
        limit_price=None,
        quote=quote_fixture(),
    )

    assert pairs(executions) == [(Decimal("10.00"), 100), (Decimal("10.01"), 200)]


def test_market_order_returns_partial_fill_when_visible_depth_is_insufficient() -> None:
    executions = match_visible_depth(
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        remaining=2_000,
        limit_price=None,
        quote=quote_fixture(),
    )

    assert sum(execution.quantity for execution in executions) == 1_500


@pytest.mark.parametrize(
    ("side", "limit_price"),
    [(OrderSide.BUY, Decimal("9.99")), (OrderSide.SELL, Decimal("10.00"))],
)
def test_limit_order_returns_no_execution_when_best_price_is_unacceptable(
    side: OrderSide, limit_price: Decimal
) -> None:
    assert (
        match_visible_depth(
            side=side,
            order_type=OrderType.LIMIT,
            remaining=100,
            limit_price=limit_price,
            quote=quote_fixture(),
        )
        == []
    )


def test_zero_quantity_level_is_skipped_without_hiding_later_depth() -> None:
    executions = match_visible_depth(
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        remaining=150,
        limit_price=None,
        quote=quote_fixture(
            asks=[
                ("10.00", 0),
                ("10.01", 100),
                ("10.02", 0),
                ("10.03", 100),
                ("10.04", 100),
            ]
        ),
    )

    assert pairs(executions) == [(Decimal("10.01"), 100), (Decimal("10.03"), 50)]
    assert all(execution.quantity > 0 for execution in executions)


@pytest.mark.parametrize("remaining", [0, -1, True, Decimal("1")])
def test_rejects_non_strict_positive_integer_remaining(remaining: object) -> None:
    with pytest.raises(PaperTradingError) as caught:
        match_visible_depth(
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            remaining=remaining,  # type: ignore[arg-type]
            limit_price=None,
            quote=quote_fixture(),
        )
    assert caught.value.code == "invalid_match_input"


@pytest.mark.parametrize(
    ("side", "order_type"),
    [("hold", OrderType.MARKET), (OrderSide.BUY, "stop")],
)
def test_rejects_unknown_side_or_order_type(side: object, order_type: object) -> None:
    with pytest.raises(PaperTradingError) as caught:
        match_visible_depth(
            side=side,  # type: ignore[arg-type]
            order_type=order_type,  # type: ignore[arg-type]
            remaining=100,
            limit_price=None,
            quote=quote_fixture(),
        )
    assert caught.value.code == "invalid_match_input"


@pytest.mark.parametrize(
    "limit_price", [None, Decimal("0"), Decimal("-1"), Decimal("NaN"), Decimal("Infinity")]
)
def test_limit_order_requires_finite_positive_limit(limit_price: Decimal | None) -> None:
    with pytest.raises(PaperTradingError) as caught:
        match_visible_depth(
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            remaining=100,
            limit_price=limit_price,
            quote=quote_fixture(),
        )
    assert caught.value.code == "invalid_match_input"


def test_market_order_rejects_limit_price() -> None:
    with pytest.raises(PaperTradingError) as caught:
        match_visible_depth(
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            remaining=100,
            limit_price=Decimal("10.00"),
            quote=quote_fixture(),
        )
    assert caught.value.code == "invalid_match_input"


def test_rejects_suspended_quote() -> None:
    with pytest.raises(PaperTradingError) as caught:
        match_visible_depth(
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            remaining=100,
            limit_price=None,
            quote=quote_fixture(suspended=True),
        )
    assert caught.value.code == "suspended_security"


@pytest.mark.parametrize(
    "quote",
    [
        quote_fixture(
            asks=[("10.00", 100), ("10.02", 100), ("10.01", 100), ("10.03", 100), ("10.04", 100)]
        ),
        quote_fixture(
            bids=[("9.99", 100), ("9.97", 100), ("9.98", 100), ("9.96", 100), ("9.95", 100)]
        ),
        quote_fixture(
            bids=[("10.00", 100), ("9.98", 100), ("9.97", 100), ("9.96", 100), ("9.95", 100)]
        ),
    ],
    ids=["unordered asks", "unordered bids", "crossed book"],
)
def test_rejects_malformed_order_book(quote: RealtimeQuote) -> None:
    with pytest.raises(PaperTradingError) as caught:
        match_visible_depth(
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            remaining=100,
            limit_price=None,
            quote=quote,
        )
    assert caught.value.code == "invalid_quote"


def test_does_not_mutate_quote_and_is_deterministic() -> None:
    quote = quote_fixture()
    before = deepcopy(quote)

    first = match_visible_depth(
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        remaining=150,
        limit_price=None,
        quote=quote,
    )
    second = match_visible_depth(
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        remaining=150,
        limit_price=None,
        quote=quote,
    )

    assert first == second
    assert quote == before


def test_preserves_decimal_price_precision() -> None:
    quote = quote_fixture(
        asks=[
            ("10.0001", 100),
            ("10.0002", 100),
            ("10.0003", 100),
            ("10.0004", 100),
            ("10.0005", 100),
        ]
    )
    execution = match_visible_depth(
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        remaining=1,
        limit_price=Decimal("10.0001"),
        quote=quote,
    )[0]

    assert execution.price == Decimal("10.0001")


def test_execution_is_frozen_and_strict() -> None:
    execution = Execution(price=Decimal("10.00"), quantity=1)
    with pytest.raises(ValidationError):
        execution.quantity = 2
    with pytest.raises(ValidationError):
        Execution(price=Decimal("10.00"), quantity=True)
