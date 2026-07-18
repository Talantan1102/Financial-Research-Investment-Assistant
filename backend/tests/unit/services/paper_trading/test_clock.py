from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from app.services.paper_trading.clock import FixedTradingCalendar, TradingClock
from app.services.paper_trading.types import MarketPhase

SHANGHAI = ZoneInfo("Asia/Shanghai")
UTC = ZoneInfo("UTC")
OPEN_DATE = date(2026, 7, 20)


def _clock() -> TradingClock:
    return TradingClock(FixedTradingCalendar({OPEN_DATE}))


def test_market_phases_and_next_open_day() -> None:
    calendar = FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)})
    clock = TradingClock(calendar)

    assert clock.phase(datetime(2026, 7, 20, 10, 0, tzinfo=SHANGHAI)) == (
        MarketPhase.MORNING
    )
    assert clock.phase(datetime(2026, 7, 20, 9, 20, tzinfo=SHANGHAI)) == (
        MarketPhase.OPENING_AUCTION
    )
    assert clock.phase(datetime(2026, 7, 20, 12, 0, tzinfo=SHANGHAI)) == (
        MarketPhase.LUNCH
    )
    assert clock.phase(datetime(2026, 7, 20, 14, 58, tzinfo=SHANGHAI)) == (
        MarketPhase.CLOSING_AUCTION
    )
    assert clock.phase(datetime(2026, 7, 20, 15, 1, tzinfo=SHANGHAI)) == (
        MarketPhase.CLOSED
    )
    assert calendar.next_open_date(date(2026, 7, 20)) == date(2026, 7, 21)


@pytest.mark.parametrize(
    ("at", "expected"),
    [
        ((9, 14, 59), MarketPhase.CLOSED),
        ((9, 15, 0), MarketPhase.OPENING_AUCTION),
        ((9, 25, 0), MarketPhase.CLOSED),
        ((9, 30, 0), MarketPhase.MORNING),
        ((11, 30, 0), MarketPhase.LUNCH),
        ((13, 0, 0), MarketPhase.AFTERNOON),
        ((14, 57, 0), MarketPhase.CLOSING_AUCTION),
        ((15, 0, 0), MarketPhase.CLOSED),
    ],
)
def test_phase_boundaries(at: tuple[int, int, int], expected: MarketPhase) -> None:
    hour, minute, second = at

    assert _clock().phase(
        datetime(2026, 7, 20, hour, minute, second, tzinfo=SHANGHAI)
    ) == expected


def test_non_open_date_is_closed() -> None:
    assert _clock().phase(datetime(2026, 7, 21, 10, 0, tzinfo=SHANGHAI)) == (
        MarketPhase.CLOSED
    )


def test_phase_converts_non_shanghai_timezone() -> None:
    assert _clock().phase(datetime(2026, 7, 20, 2, 0, tzinfo=UTC)) == (
        MarketPhase.MORNING
    )


def test_next_open_date_raises_when_no_future_date_is_configured() -> None:
    calendar = FixedTradingCalendar({OPEN_DATE})

    with pytest.raises(LookupError, match="no future open date configured"):
        calendar.next_open_date(OPEN_DATE)
