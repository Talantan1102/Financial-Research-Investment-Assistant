import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, DecimalException, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.types import RuleSet

_BUILTIN_FIXTURE = Path(__file__).with_name("rules") / "a_share_20260706.json"
_MIN_SUPPORTED_PRICE = Decimal("0.0001")
_MAX_SUPPORTED_PRICE = Decimal("99999999999999.9999")


@dataclass(frozen=True)
class _BoardLimits:
    normal: Decimal
    risk_warning: Decimal


class RuleBook:
    def __init__(self, fixture: dict[str, Any]) -> None:
        try:
            self._version = _require_string(fixture, "version")
            self._effective_from = date.fromisoformat(_require_string(fixture, "effective_from"))
            defaults = _require_mapping(fixture, "defaults")
            self._buy_lot_size = _require_positive_int(defaults, "buy_lot_size")
            self._price_tick = _require_supported_price(defaults, "price_tick")
            self._quote_freshness_seconds = _require_positive_int(
                defaults, "quote_freshness_seconds"
            )

            raw_boards = _require_mapping(fixture, "boards")
            normalized_boards: dict[str, _BoardLimits] = {}
            for board, raw_limits in raw_boards.items():
                if not isinstance(board, str):
                    raise TypeError("board name must be a string")
                if not isinstance(raw_limits, dict):
                    raise TypeError(f"{board} must be an object")
                normalized_boards[board] = _BoardLimits(
                    normal=_require_ratio(
                        raw_limits,
                        "normal_limit_ratio",
                        field=f"{board}.normal_limit_ratio",
                    ),
                    risk_warning=_require_ratio(
                        raw_limits,
                        "risk_warning_limit_ratio",
                        field=f"{board}.risk_warning_limit_ratio",
                    ),
                )
            self._boards: Mapping[str, _BoardLimits] = MappingProxyType(normalized_boards)
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError(f"invalid A-share rulebook fixture: {exc}") from exc

    @classmethod
    def from_builtin_fixture(cls) -> "RuleBook":
        try:
            fixture = json.loads(
                _BUILTIN_FIXTURE.read_text(encoding="utf-8"),
                parse_float=Decimal,
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot load A-share rulebook fixture: {exc}") from exc
        if not isinstance(fixture, dict):
            raise ValueError("invalid A-share rulebook fixture: root must be an object")
        return cls(fixture)

    def resolve(
        self,
        *,
        ts_code: str,
        board: str,
        risk_warning: bool,
        side: str,
        on: date,
        special_regime: str | None = None,
    ) -> RuleSet:
        del ts_code
        if special_regime is not None:
            raise PaperTradingError("unsupported_trading_regime", "首版不支持该特殊交易阶段")
        if on < self._effective_from:
            raise PaperTradingError("unsupported_trading_regime", "规则尚未生效")
        if side == "buy":
            resolved_side: Literal["buy", "sell"] = "buy"
        elif side == "sell":
            resolved_side = "sell"
        else:
            raise PaperTradingError("unsupported_trading_regime", "不支持的交易方向")

        board_rules = self._boards.get(board)
        if board_rules is None:
            raise PaperTradingError("unsupported_trading_regime", "不支持的交易板块")
        price_limit_ratio = board_rules.risk_warning if risk_warning else board_rules.normal

        return RuleSet(
            version=self._version,
            effective_from=self._effective_from,
            board=board,
            risk_warning=risk_warning,
            side=resolved_side,
            buy_lot_size=self._buy_lot_size,
            price_tick=self._price_tick,
            price_limit_ratio=price_limit_ratio,
            quote_freshness_seconds=self._quote_freshness_seconds,
        )

    def validate_quantity(self, rules: RuleSet, quantity: int, current_holding: int = 0) -> None:
        if quantity <= 0:
            raise PaperTradingError("invalid_lot_size", "委托数量必须大于零")

        lot_size = rules.buy_lot_size
        if rules.side == "buy":
            if quantity % lot_size:
                raise PaperTradingError("invalid_lot_size", "买入数量必须为整手")
            return

        if rules.side == "sell":
            if quantity > current_holding:
                raise PaperTradingError("insufficient_sellable_quantity", "卖出数量超过当前持仓")
            if quantity % lot_size == 0:
                return

            remainder = current_holding % lot_size
            if remainder > 0 and quantity in {current_holding, remainder}:
                return
            raise PaperTradingError("invalid_lot_size", "零股卖出必须一次申报全部零股")

        raise PaperTradingError("unsupported_trading_regime", "不支持的交易方向")

    def price_bounds(self, rules: RuleSet, previous_close: Decimal) -> tuple[Decimal, Decimal]:
        if (
            not previous_close.is_finite()
            or previous_close < _MIN_SUPPORTED_PRICE
            or previous_close > _MAX_SUPPORTED_PRICE
        ):
            raise PaperTradingError("invalid_price", "昨收价超出支持的价格范围")

        ratio = rules.price_limit_ratio
        tick = rules.price_tick
        try:
            lower = _round_to_tick(previous_close * (Decimal("1") - ratio), tick)
            upper = _round_to_tick(previous_close * (Decimal("1") + ratio), tick)
        except DecimalException as exc:
            raise PaperTradingError(
                "invalid_price",
                "价格边界无法表示为支持的小数范围",
            ) from exc
        if (
            lower < _MIN_SUPPORTED_PRICE
            or lower > _MAX_SUPPORTED_PRICE
            or upper < _MIN_SUPPORTED_PRICE
            or upper > _MAX_SUPPORTED_PRICE
        ):
            raise PaperTradingError(
                "invalid_price",
                "价格边界超出 Numeric(18, 4) 支持范围",
            )
        return lower, upper


def _require_mapping(value: dict[str, Any], key: str) -> dict[str, Any]:
    item = value[key]
    if not isinstance(item, dict):
        raise TypeError(f"{key} must be an object")
    return item


def _require_string(value: dict[str, Any], key: str) -> str:
    item = value[key]
    if not isinstance(item, str):
        raise TypeError(f"{key} must be a string")
    return item


def _require_int(value: dict[str, Any], key: str) -> int:
    item = value[key]
    if isinstance(item, bool) or not isinstance(item, int):
        raise TypeError(f"{key} must be an integer")
    return item


def _require_positive_int(value: dict[str, Any], key: str) -> int:
    item = _require_int(value, key)
    if item <= 0:
        raise ValueError(f"{key} must be positive")
    return item


def _require_positive_decimal(
    value: dict[str, Any], key: str, *, field: str | None = None
) -> Decimal:
    field = field or key
    if key not in value:
        raise KeyError(field)
    item = value[key]
    if not isinstance(item, str):
        raise TypeError(f"{field} must be a numeric string")
    try:
        decimal_value = Decimal(item)
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a valid decimal") from exc
    if not decimal_value.is_finite() or decimal_value <= 0:
        raise ValueError(f"{field} must be positive and finite")
    return decimal_value


def _require_ratio(value: dict[str, Any], key: str, *, field: str) -> Decimal:
    ratio = _require_positive_decimal(value, key, field=field)
    if ratio >= 1:
        raise ValueError(f"{field} must be less than one")
    return ratio


def _require_supported_price(value: dict[str, Any], key: str) -> Decimal:
    price = _require_positive_decimal(value, key)
    if price < _MIN_SUPPORTED_PRICE or price > _MAX_SUPPORTED_PRICE:
        raise ValueError(f"{key} must fit Numeric(18, 4)")
    return price


def _round_to_tick(value: Decimal, tick: Decimal) -> Decimal:
    rounded_units = (value / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return (rounded_units * tick).quantize(tick)
