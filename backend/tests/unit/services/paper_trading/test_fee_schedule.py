import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast

import pytest
from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.fee_schedule import FeeSchedule

FIXTURE_PATH = (
    Path(__file__).parents[4]
    / "app"
    / "services"
    / "paper_trading"
    / "rules"
    / "fees_cn_a_20230828.json"
)
OFFICIAL_SOURCES = (
    "https://fgk.chinatax.gov.cn/zcfgk/c102416/c5211343/content.html",
    "https://www.chinaclear.cn/zdjs/gszb/202204/f89e788c65a241e88e7f0d0348de586f.shtml",
    "https://www.sse.com.cn/lawandrules/sselawsrules2025/charge/c/c_20250610_10781461.shtml",
    "https://www.szse.cn/marketServices/deal/payFees/index.html",
)


def _valid_fixture() -> dict[str, Any]:
    return {
        "version": "test-fees-v1",
        "effective_from": "2023-08-28",
        "verified_on": "2026-07-18",
        "sources": list(OFFICIAL_SOURCES),
        "statutory_rates": {
            "sell_stamp_duty": "0.0005",
            "transfer_fee": "0.00001",
        },
    }


def test_fee_schedule_applies_direction_and_minimum_commission() -> None:
    schedule = FeeSchedule.from_builtin_fixture()

    buy = schedule.calculate(side="buy", gross=Decimal("1000"))
    sell = schedule.calculate(side="sell", gross=Decimal("1000"))

    assert buy.commission == Decimal("5.00")
    assert buy.stamp_duty == Decimal("0.00")
    assert buy.transfer_fee == Decimal("0.01")
    assert buy.total == Decimal("5.01")
    assert sell.commission == Decimal("5.00")
    assert sell.stamp_duty == Decimal("0.50")
    assert sell.transfer_fee == Decimal("0.01")
    assert sell.total == Decimal("5.51")


def test_fee_schedule_uses_configurable_commission_and_rounds_half_up() -> None:
    fees = FeeSchedule.from_builtin_fixture().calculate(
        side="sell",
        gross=Decimal("1010"),
        commission_rate=Decimal("0.005"),
        minimum_commission=Decimal("0"),
    )

    assert fees.commission == Decimal("5.05")
    assert fees.stamp_duty == Decimal("0.51")
    assert fees.transfer_fee == Decimal("0.01")


def test_builtin_fixture_has_versioned_rates_and_official_sources() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    schedule = FeeSchedule.from_builtin_fixture()

    assert fixture["version"] == "cn-a-fees-2023-08-28-v1"
    assert schedule.version == "cn-a-fees-2023-08-28-v1"
    assert schedule.effective_from == date(2023, 8, 28)
    assert schedule.verified_on == date(2026, 7, 18)
    assert schedule.sources == OFFICIAL_SOURCES
    assert schedule.sell_stamp_duty_rate == Decimal("0.0005")
    assert schedule.transfer_fee_rate == Decimal("0.00001")


@pytest.mark.parametrize(
    ("side", "gross", "commission_rate", "minimum_commission"),
    [
        ("hold", Decimal("1000"), Decimal("0.0003"), Decimal("5")),
        ("buy", Decimal("0"), Decimal("0.0003"), Decimal("5")),
        ("buy", Decimal("-1"), Decimal("0.0003"), Decimal("5")),
        ("buy", Decimal("NaN"), Decimal("0.0003"), Decimal("5")),
        ("buy", Decimal("1e999999"), Decimal("0.0003"), Decimal("5")),
        ("buy", Decimal("1000"), Decimal("-0.1"), Decimal("5")),
        ("buy", Decimal("1000"), Decimal("Infinity"), Decimal("5")),
        ("buy", Decimal("1000"), Decimal("0.0003"), Decimal("-1")),
        ("buy", Decimal("1000"), Decimal("0.0003"), Decimal("NaN")),
        ("buy", Decimal("1000"), Decimal("0.0003"), Decimal("1e999999")),
    ],
)
def test_fee_schedule_rejects_invalid_calculation_inputs(
    side: str,
    gross: Decimal,
    commission_rate: Decimal,
    minimum_commission: Decimal,
) -> None:
    with pytest.raises(PaperTradingError) as caught:
        FeeSchedule.from_builtin_fixture().calculate(
            side=cast(Literal["buy", "sell"], side),
            gross=gross,
            commission_rate=commission_rate,
            minimum_commission=minimum_commission,
        )

    assert caught.value.code == "invalid_fee_input"


@pytest.mark.parametrize(
    ("mutate", "expected_context"),
    [
        (lambda fixture: fixture.update(version=""), "version"),
        (lambda fixture: fixture.update(effective_from="not-a-date"), "effective_from"),
        (lambda fixture: fixture.update(verified_on="not-a-date"), "verified_on"),
        (lambda fixture: fixture.update(sources=[]), "sources"),
        (
            lambda fixture: fixture["statutory_rates"].update(sell_stamp_duty="Infinity"),
            "sell_stamp_duty",
        ),
        (
            lambda fixture: fixture["statutory_rates"].update(transfer_fee="0"),
            "transfer_fee",
        ),
        (
            lambda fixture: fixture["statutory_rates"].update(transfer_fee="1"),
            "transfer_fee",
        ),
    ],
)
def test_fee_schedule_rejects_invalid_fixture_at_construction(
    mutate: Any, expected_context: str
) -> None:
    fixture = _valid_fixture()
    mutate(fixture)

    with pytest.raises(ValueError, match="^invalid fee schedule fixture:") as caught:
        FeeSchedule(fixture)

    assert expected_context in str(caught.value)


def test_fee_schedule_is_an_immutable_snapshot_of_fixture() -> None:
    fixture = _valid_fixture()
    schedule = FeeSchedule(fixture)

    fixture["version"] = "changed"
    fixture["sources"].append("https://example.invalid")
    fixture["statutory_rates"]["sell_stamp_duty"] = "0.9"

    assert schedule.version == "test-fees-v1"
    assert schedule.sources == OFFICIAL_SOURCES
    assert schedule.sell_stamp_duty_rate == Decimal("0.0005")
