"""Deterministic matching against the visible five-level order book."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.paper_order import OrderSide, OrderType
from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.types import QuoteLevel, RealtimeQuote


class Execution(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    price: Decimal = Field(gt=0)
    quantity: int = Field(gt=0)


def match_visible_depth(
    *,
    side: OrderSide | str,
    order_type: OrderType | str,
    remaining: int,
    limit_price: Decimal | None,
    quote: RealtimeQuote,
) -> list[Execution]:
    """Match one order without mutating the quote or performing I/O."""
    normalized_side = _side(side)
    normalized_type = _order_type(order_type)
    _validate_order_input(normalized_type, remaining, limit_price)
    _validate_quote(quote)

    visible_levels = quote.asks if normalized_side is OrderSide.BUY else quote.bids
    levels = tuple(level for level in visible_levels if level.quantity > 0)
    executions: list[Execution] = []
    left = remaining
    for level in levels:
        if left == 0 or not _price_is_acceptable(
            level,
            side=normalized_side,
            order_type=normalized_type,
            limit_price=limit_price,
        ):
            break
        used = min(left, level.quantity)
        executions.append(Execution(price=level.price, quantity=used))
        left -= used
    return executions


def _side(value: OrderSide | str) -> OrderSide:
    try:
        return OrderSide(value)
    except (TypeError, ValueError) as exc:
        raise PaperTradingError("invalid_match_input", "invalid order side") from exc


def _order_type(value: OrderType | str) -> OrderType:
    try:
        return OrderType(value)
    except (TypeError, ValueError) as exc:
        raise PaperTradingError("invalid_match_input", "invalid order type") from exc


def _validate_order_input(
    order_type: OrderType, remaining: int, limit_price: Decimal | None
) -> None:
    if isinstance(remaining, bool) or not isinstance(remaining, int) or remaining <= 0:
        raise PaperTradingError("invalid_match_input", "remaining quantity must be positive")
    if order_type is OrderType.MARKET:
        if limit_price is not None:
            raise PaperTradingError("invalid_match_input", "market order cannot have limit price")
        return
    if not isinstance(limit_price, Decimal) or not limit_price.is_finite() or limit_price <= 0:
        raise PaperTradingError("invalid_match_input", "limit price must be finite and positive")


def _validate_quote(quote: RealtimeQuote) -> None:
    if quote.suspended:
        raise PaperTradingError("suspended_security", "security is suspended")
    bids = tuple(level for level in quote.bids if level.quantity > 0)
    asks = tuple(level for level in quote.asks if level.quantity > 0)
    if any(left.price <= right.price for left, right in zip(bids, bids[1:])) or any(
        left.price >= right.price for left, right in zip(asks, asks[1:])
    ):
        raise PaperTradingError("quote_unavailable", "quote levels are not best-price first")
    if bids and asks and bids[0].price >= asks[0].price:
        raise PaperTradingError("quote_unavailable", "quote order book is crossed")


def _price_is_acceptable(
    level: QuoteLevel,
    *,
    side: OrderSide,
    order_type: OrderType,
    limit_price: Decimal | None,
) -> bool:
    if order_type is OrderType.MARKET:
        return True
    assert limit_price is not None
    if side is OrderSide.BUY:
        return level.price <= limit_price
    return level.price >= limit_price
