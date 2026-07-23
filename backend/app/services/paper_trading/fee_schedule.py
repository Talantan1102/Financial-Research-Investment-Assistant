import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, DecimalException, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.types import FeeBreakdown

_BUILTIN_FIXTURE = Path(__file__).with_name("rules") / "fees_cn_a_20230828.json"
_CENT = Decimal("0.01")


class FeeSchedule:
    def __init__(self, fixture: dict[str, Any]) -> None:
        try:
            self._version = _require_nonempty_string(fixture, "version")
            self._effective_from = _require_date(fixture, "effective_from")
            self._verified_on = _require_date(fixture, "verified_on")
            if self._verified_on < self._effective_from:
                raise ValueError("verified_on must not precede effective_from")
            self._sources = _require_sources(fixture)
            rates = _require_mapping(fixture, "statutory_rates")
            self._sell_stamp_duty_rate = _require_rate(rates, "sell_stamp_duty")
            self._transfer_fee_rate = _require_rate(rates, "transfer_fee")
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid fee schedule fixture: {exc}") from exc

    @classmethod
    def from_builtin_fixture(cls) -> "FeeSchedule":
        try:
            fixture = json.loads(_BUILTIN_FIXTURE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot load fee schedule fixture: {exc}") from exc
        if not isinstance(fixture, dict):
            raise ValueError("invalid fee schedule fixture: root must be an object")
        return cls(fixture)

    @property
    def version(self) -> str:
        return self._version

    @property
    def effective_from(self) -> date:
        return self._effective_from

    @property
    def verified_on(self) -> date:
        return self._verified_on

    @property
    def sources(self) -> tuple[str, ...]:
        return self._sources

    @property
    def sell_stamp_duty_rate(self) -> Decimal:
        return self._sell_stamp_duty_rate

    @property
    def transfer_fee_rate(self) -> Decimal:
        return self._transfer_fee_rate

    def calculate(
        self,
        *,
        side: Literal["buy", "sell"],
        gross: Decimal,
        on: date,
        commission_rate: Decimal = Decimal("0.0003"),
        minimum_commission: Decimal = Decimal("5.00"),
    ) -> FeeBreakdown:
        if on < self._effective_from:
            raise PaperTradingError(
                "fee_schedule_not_effective",
                "fee schedule is not effective on the execution date",
            )
        resolved_side = _require_side(side)
        _validate_calculation_decimal(gross, "gross", positive=True)
        _validate_calculation_decimal(commission_rate, "commission_rate")
        _validate_calculation_decimal(minimum_commission, "minimum_commission")
        if commission_rate >= 1:
            raise PaperTradingError("invalid_fee_input", "commission_rate must be less than one")

        try:
            commission = _round_cents(max(minimum_commission, gross * commission_rate))
            stamp_duty = _round_cents(
                gross * self._sell_stamp_duty_rate if resolved_side == "sell" else Decimal(0)
            )
            transfer_fee = _round_cents(gross * self._transfer_fee_rate)
        except DecimalException as exc:
            raise PaperTradingError(
                "invalid_fee_input", "fee values cannot be represented in cents"
            ) from exc
        return FeeBreakdown(
            commission=commission,
            stamp_duty=stamp_duty,
            transfer_fee=transfer_fee,
        )


def _require_mapping(value: dict[str, Any], key: str) -> dict[str, Any]:
    item = value[key]
    if not isinstance(item, dict):
        raise TypeError(f"{key} must be an object")
    return item


def _require_nonempty_string(value: dict[str, Any], key: str) -> str:
    item = value[key]
    if not isinstance(item, str) or not item.strip():
        raise TypeError(f"{key} must be a non-empty string")
    return item


def _require_date(value: dict[str, Any], key: str) -> date:
    raw = _require_nonempty_string(value, key)
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be an ISO date") from exc


def _require_sources(value: dict[str, Any]) -> tuple[str, ...]:
    sources = value["sources"]
    if not isinstance(sources, list) or not sources:
        raise TypeError("sources must be a non-empty list")
    if any(not isinstance(source, str) or not source.startswith("https://") for source in sources):
        raise TypeError("sources must contain HTTPS URLs")
    return tuple(sources)


def _require_rate(value: dict[str, Any], key: str) -> Decimal:
    raw = value[key]
    if not isinstance(raw, str):
        raise TypeError(f"{key} must be a numeric string")
    try:
        rate = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"{key} must be a valid decimal") from exc
    if not rate.is_finite() or rate <= 0 or rate >= 1:
        raise ValueError(f"{key} must be finite and between zero and one")
    return rate


def _require_side(side: str) -> Literal["buy", "sell"]:
    if side == "buy":
        return "buy"
    if side == "sell":
        return "sell"
    raise PaperTradingError("invalid_fee_input", "side must be buy or sell")


def _validate_calculation_decimal(value: Decimal, field: str, *, positive: bool = False) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise PaperTradingError("invalid_fee_input", f"{field} must be a finite Decimal")
    if value < 0 or (positive and value == 0):
        qualifier = "positive" if positive else "non-negative"
        raise PaperTradingError("invalid_fee_input", f"{field} must be {qualifier}")


def _round_cents(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)
