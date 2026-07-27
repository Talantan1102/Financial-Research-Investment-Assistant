import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.rulebook import RuleBook
from app.services.paper_trading.types import RuleSet

EFFECTIVE_DATE = date(2026, 7, 6)
FIXTURE_PATH = (
    Path(__file__).parents[4]
    / "app"
    / "services"
    / "paper_trading"
    / "rules"
    / "a_share_20260706.json"
)
OFFICIAL_SOURCES = [
    "https://www.sse.com.cn/lawandrules/sselawsrules2025/fund/trading/c/c_20260424_10817739.shtml",
    "https://www.szse.cn/lawrules/rule/allrules/bussiness/t20260424_620190.html",
]


def _valid_fixture() -> dict[str, Any]:
    return {
        "version": "test-v1",
        "effective_from": "2026-07-06",
        "defaults": {
            "buy_lot_size": 100,
            "price_tick": "0.01",
            "quote_freshness_seconds": 15,
        },
        "boards": {
            "main": {
                "normal_limit_ratio": "0.10",
                "risk_warning_limit_ratio": "0.05",
            }
        },
    }


def _resolve(
    rulebook: RuleBook,
    *,
    board: str = "main",
    risk_warning: bool = False,
    side: str = "buy",
    on: date = date(2026, 7, 20),
    special_regime: str | None = None,
) -> RuleSet:
    return rulebook.resolve(
        ts_code="600519.SH",
        board=board,
        risk_warning=risk_warning,
        side=side,
        on=on,
        special_regime=special_regime,
    )


def test_rulebook_selects_board_and_risk_warning() -> None:
    rulebook = RuleBook.from_builtin_fixture()

    main = _resolve(rulebook)
    main_risk_warning = _resolve(rulebook, risk_warning=True)
    star = _resolve(rulebook, board="star")
    chinext = _resolve(rulebook, board="chinext")

    assert main.price_limit_ratio == Decimal("0.10")
    assert main_risk_warning.price_limit_ratio == Decimal("0.05")
    assert star.price_limit_ratio == Decimal("0.20")
    assert chinext.price_limit_ratio == Decimal("0.20")


def test_rulebook_returns_exact_fixture_metadata_and_defaults() -> None:
    rules = _resolve(RuleBook.from_builtin_fixture(), side="sell")

    assert rules.version == "cn-a-2026-07-06-v1"
    assert rules.effective_from == EFFECTIVE_DATE
    assert rules.side == "sell"
    assert rules.buy_lot_size == 100
    assert rules.price_tick == Decimal("0.01")
    assert rules.quote_freshness_seconds == 15


def test_rulebook_fixture_has_exact_official_sources() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert fixture["verified_on"] == "2026-07-18"
    assert fixture["sources"] == OFFICIAL_SOURCES


def test_rulebook_does_not_leak_float_values_into_ruleset() -> None:
    rules = _resolve(RuleBook.from_builtin_fixture())

    assert all(not isinstance(value, float) for value in rules.model_dump().values())


@pytest.mark.parametrize(
    ("path", "bad_value", "expected_context"),
    [
        (("defaults", "buy_lot_size"), -100, "buy_lot_size"),
        (("defaults", "quote_freshness_seconds"), 0, "quote_freshness_seconds"),
        (("defaults", "price_tick"), "NaN", "price_tick"),
        (("boards", "main", "normal_limit_ratio"), "-0.10", "main.normal_limit_ratio"),
        (
            ("boards", "main", "risk_warning_limit_ratio"),
            "Infinity",
            "main.risk_warning_limit_ratio",
        ),
    ],
)
def test_rulebook_rejects_semantically_invalid_fixture_at_construction(
    path: tuple[str, ...], bad_value: object, expected_context: str
) -> None:
    fixture = _valid_fixture()
    target = fixture
    for key in path[:-1]:
        target = cast(dict[str, Any], target[key])
    target[path[-1]] = bad_value

    with pytest.raises(ValueError, match="^invalid A-share rulebook fixture:") as caught:
        RuleBook(fixture)

    assert expected_context in str(caught.value)


@pytest.mark.parametrize(
    ("field", "ratio"),
    [
        ("normal_limit_ratio", "1.00"),
        ("normal_limit_ratio", "1.20"),
        ("risk_warning_limit_ratio", "1.00"),
        ("risk_warning_limit_ratio", "1.20"),
    ],
)
def test_rulebook_rejects_price_limit_ratio_at_or_above_one(field: str, ratio: str) -> None:
    fixture = _valid_fixture()
    boards = cast(dict[str, Any], fixture["boards"])
    main = cast(dict[str, Any], boards["main"])
    main[field] = ratio

    with pytest.raises(ValueError, match="^invalid A-share rulebook fixture:") as caught:
        RuleBook(fixture)

    assert f"main.{field}" in str(caught.value)


def test_rulebook_accepts_very_small_positive_price_limit_ratio() -> None:
    fixture = _valid_fixture()
    boards = cast(dict[str, Any], fixture["boards"])
    main = cast(dict[str, Any], boards["main"])
    main["normal_limit_ratio"] = "0.000001"

    resolved = _resolve(RuleBook(fixture))

    assert resolved.price_limit_ratio == Decimal("0.000001")


def test_rulebook_missing_board_ratio_reports_board_context() -> None:
    fixture = _valid_fixture()
    boards = cast(dict[str, Any], fixture["boards"])
    main = cast(dict[str, Any], boards["main"])
    del main["risk_warning_limit_ratio"]

    with pytest.raises(ValueError) as caught:
        RuleBook(fixture)

    assert "main.risk_warning_limit_ratio" in str(caught.value)


def test_rulebook_is_an_immutable_snapshot_of_fixture() -> None:
    fixture = _valid_fixture()
    rulebook = RuleBook(fixture)

    defaults = cast(dict[str, Any], fixture["defaults"])
    boards = cast(dict[str, Any], fixture["boards"])
    main = cast(dict[str, Any], boards["main"])
    defaults["buy_lot_size"] = 1
    main["normal_limit_ratio"] = "0.99"

    resolved = _resolve(rulebook)
    assert resolved.buy_lot_size == 100
    assert resolved.price_limit_ratio == Decimal("0.10")


def test_special_regime_fails_closed() -> None:
    with pytest.raises(PaperTradingError) as caught:
        _resolve(RuleBook.from_builtin_fixture(), special_regime="first_day")

    assert caught.value.code == "unsupported_trading_regime"
    assert str(caught.value) == "首版不支持该特殊交易阶段"


@pytest.mark.parametrize(
    ("overrides", "expected_message"),
    [
        ({"board": "bse"}, "不支持的交易板块"),
        ({"side": "hold"}, "不支持的交易方向"),
        ({"on": date(2026, 7, 5)}, "规则尚未生效"),
    ],
)
def test_unsupported_resolution_fails_closed(
    overrides: dict[str, object], expected_message: str
) -> None:
    with pytest.raises(PaperTradingError) as caught:
        _resolve(RuleBook.from_builtin_fixture(), **overrides)  # type: ignore[arg-type]

    assert caught.value.code == "unsupported_trading_regime"
    assert str(caught.value) == expected_message


def test_buy_quantity_requires_round_lot() -> None:
    rulebook = RuleBook.from_builtin_fixture()
    rules = _resolve(rulebook, side="buy")

    rulebook.validate_quantity(rules, 100)
    with pytest.raises(PaperTradingError) as caught:
        rulebook.validate_quantity(rules, 150)

    assert caught.value.code == "invalid_lot_size"


def test_quantity_must_be_positive() -> None:
    rulebook = RuleBook.from_builtin_fixture()
    rules = _resolve(rulebook)

    with pytest.raises(PaperTradingError) as caught:
        rulebook.validate_quantity(rules, 0)

    assert caught.value.code == "invalid_lot_size"


def test_sell_accepts_round_lot_and_allowed_odd_lot_disposals() -> None:
    rulebook = RuleBook.from_builtin_fixture()
    rules = _resolve(rulebook, side="sell")

    rulebook.validate_quantity(rules, 100, current_holding=250)
    rulebook.validate_quantity(rules, 250, current_holding=250)
    rulebook.validate_quantity(rules, 50, current_holding=250)


@pytest.mark.parametrize(
    ("quantity", "current_holding"),
    [(25, 250), (150, 250), (50, 200)],
)
def test_sell_rejects_other_non_round_quantities(quantity: int, current_holding: int) -> None:
    rulebook = RuleBook.from_builtin_fixture()
    rules = _resolve(rulebook, side="sell")

    with pytest.raises(PaperTradingError) as caught:
        rulebook.validate_quantity(rules, quantity, current_holding)

    assert caught.value.code == "invalid_lot_size"


def test_sell_rejects_quantity_above_holding() -> None:
    rulebook = RuleBook.from_builtin_fixture()
    rules = _resolve(rulebook, side="sell")

    with pytest.raises(PaperTradingError) as caught:
        rulebook.validate_quantity(rules, 300, current_holding=250)

    assert caught.value.code == "insufficient_sellable_quantity"


def test_sell_without_current_holding_fails_closed() -> None:
    rulebook = RuleBook.from_builtin_fixture()
    rules = _resolve(rulebook, side="sell")

    with pytest.raises(PaperTradingError) as caught:
        rulebook.validate_quantity(rules, 100)

    assert caught.value.code == "insufficient_sellable_quantity"


def test_validate_quantity_rejects_bypassed_invalid_side() -> None:
    rulebook = RuleBook.from_builtin_fixture()
    invalid_rules = _resolve(rulebook).model_copy(update={"side": "hold"})

    with pytest.raises(PaperTradingError) as caught:
        rulebook.validate_quantity(invalid_rules, 100, current_holding=100)

    assert caught.value.code == "unsupported_trading_regime"


@pytest.mark.parametrize(
    ("previous_close", "expected"),
    [
        (Decimal("10.00"), (Decimal("9.00"), Decimal("11.00"))),
        (Decimal("12.34"), (Decimal("11.11"), Decimal("13.57"))),
    ],
)
def test_price_bounds_round_half_up_to_price_tick(
    previous_close: Decimal, expected: tuple[Decimal, Decimal]
) -> None:
    rulebook = RuleBook.from_builtin_fixture()

    assert rulebook.price_bounds(_resolve(rulebook), previous_close) == expected


@pytest.mark.parametrize(
    ("previous_close", "expected"),
    [
        (Decimal("10.23"), (Decimal("9.20"), Decimal("11.25"))),
        (Decimal("10.25"), (Decimal("9.25"), Decimal("11.30"))),
    ],
)
def test_price_bounds_rounds_to_arbitrary_tick_including_half_ties(
    previous_close: Decimal, expected: tuple[Decimal, Decimal]
) -> None:
    fixture = _valid_fixture()
    defaults = cast(dict[str, Any], fixture["defaults"])
    defaults["price_tick"] = "0.05"
    rulebook = RuleBook(fixture)

    assert rulebook.price_bounds(_resolve(rulebook), previous_close) == expected


def test_price_bounds_rejects_nonpositive_previous_close() -> None:
    rulebook = RuleBook.from_builtin_fixture()

    with pytest.raises(PaperTradingError) as caught:
        rulebook.price_bounds(_resolve(rulebook), Decimal("0"))

    assert caught.value.code == "invalid_price"


@pytest.mark.parametrize(
    "previous_close", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")]
)
def test_price_bounds_rejects_nonfinite_previous_close(previous_close: Decimal) -> None:
    rulebook = RuleBook.from_builtin_fixture()

    with pytest.raises(PaperTradingError) as caught:
        rulebook.price_bounds(_resolve(rulebook), previous_close)

    assert caught.value.code == "invalid_price"


@pytest.mark.parametrize(
    "previous_close",
    [
        Decimal("1e999999"),
        Decimal("1e-999999"),
        Decimal("99999999999999.9999"),
    ],
)
def test_price_bounds_rejects_values_outside_numeric_price_capacity(
    previous_close: Decimal,
) -> None:
    rulebook = RuleBook.from_builtin_fixture()

    with pytest.raises(PaperTradingError) as caught:
        rulebook.price_bounds(_resolve(rulebook), previous_close)

    assert caught.value.code == "invalid_price"
