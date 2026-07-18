import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.types import RuleSet

_BUILTIN_FIXTURE = Path(__file__).with_name("rules") / "a_share_20260706.json"


class RuleBook:
    def __init__(self, fixture: dict[str, Any]) -> None:
        try:
            self._version = _require_string(fixture, "version")
            self._effective_from = date.fromisoformat(_require_string(fixture, "effective_from"))
            self._defaults = _require_mapping(fixture, "defaults")
            self._boards = _require_mapping(fixture, "boards")
            self._buy_lot_size = _require_int(self._defaults, "buy_lot_size")
            self._price_tick = _require_decimal(self._defaults, "price_tick")
            self._quote_freshness_seconds = _require_int(self._defaults, "quote_freshness_seconds")
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
        if side not in {"buy", "sell"}:
            raise PaperTradingError("unsupported_trading_regime", "不支持的交易方向")

        board_rules = self._boards.get(board)
        if not isinstance(board_rules, dict):
            raise PaperTradingError("unsupported_trading_regime", "不支持的交易板块")
        ratio_key = "risk_warning_limit_ratio" if risk_warning else "normal_limit_ratio"
        try:
            price_limit_ratio = _require_decimal(board_rules, ratio_key)
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError(f"invalid A-share rulebook fixture: board {board!r}: {exc}") from exc

        return RuleSet(
            version=self._version,
            effective_from=self._effective_from,
            board=board,
            risk_warning=risk_warning,
            side=side,
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

        if quantity > current_holding:
            raise PaperTradingError("insufficient_sellable_quantity", "卖出数量超过当前持仓")
        if quantity % lot_size == 0:
            return

        remainder = current_holding % lot_size
        if remainder > 0 and quantity in {current_holding, remainder}:
            return
        raise PaperTradingError("invalid_lot_size", "零股卖出必须一次申报全部零股")

    def price_bounds(self, rules: RuleSet, previous_close: Decimal) -> tuple[Decimal, Decimal]:
        if previous_close <= 0:
            raise PaperTradingError("invalid_price", "昨收价必须大于零")

        ratio = rules.price_limit_ratio
        tick = rules.price_tick
        lower = (previous_close * (Decimal("1") - ratio)).quantize(tick, rounding=ROUND_HALF_UP)
        upper = (previous_close * (Decimal("1") + ratio)).quantize(tick, rounding=ROUND_HALF_UP)
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


def _require_decimal(value: dict[str, Any], key: str) -> Decimal:
    item = value[key]
    if not isinstance(item, str):
        raise TypeError(f"{key} must be a numeric string")
    try:
        return Decimal(item)
    except InvalidOperation as exc:
        raise ValueError(f"{key} must be a valid decimal") from exc
