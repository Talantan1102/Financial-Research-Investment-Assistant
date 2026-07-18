from datetime import date, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo

import pytest
from app.services.paper_trading.clock import FixedTradingCalendar, TradingClock
from app.services.paper_trading.types import MarketPhase

SHANGHAI = ZoneInfo("Asia/Shanghai")
UTC = ZoneInfo("UTC")
LOS_ANGELES = ZoneInfo("America/Los_Angeles")
OPEN_DATE = date(2026, 7, 20)


class _IndeterminateTimezone(tzinfo):
    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        return None

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str | None:
        return "indeterminate"


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
        ((9, 24, 59), MarketPhase.OPENING_AUCTION),
        ((9, 25, 0), MarketPhase.CLOSED),
        ((9, 30, 0), MarketPhase.MORNING),
        ((11, 29, 59), MarketPhase.MORNING),
        ((11, 30, 0), MarketPhase.LUNCH),
        ((12, 59, 59), MarketPhase.LUNCH),
        ((13, 0, 0), MarketPhase.AFTERNOON),
        ((14, 56, 59), MarketPhase.AFTERNOON),
        ((14, 57, 0), MarketPhase.CLOSING_AUCTION),
        ((14, 59, 59), MarketPhase.CLOSING_AUCTION),
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


def test_phase_converts_previous_local_date_to_open_shanghai_date() -> None:
    assert _clock().phase(
        datetime(2026, 7, 19, 18, 30, tzinfo=LOS_ANGELES)
    ) == MarketPhase.MORNING


@pytest.mark.parametrize(
    "value",
    [
        datetime(2026, 7, 20, 10, 0),
        datetime(2026, 7, 20, 10, 0, tzinfo=_IndeterminateTimezone()),
    ],
)
def test_phase_rejects_datetime_without_utc_offset(value: datetime) -> None:
    with pytest.raises(ValueError, match="^timezone-aware datetime required$"):
        _clock().phase(value)


def test_calendar_snapshots_configured_open_dates() -> None:
    open_dates = {date(2026, 7, 20), date(2026, 7, 21)}
    calendar = FixedTradingCalendar(open_dates)

    open_dates.clear()

    assert calendar.is_open_date(date(2026, 7, 20))
    assert calendar.next_open_date(date(2026, 7, 20)) == date(2026, 7, 21)


def test_next_open_date_raises_when_no_future_date_is_configured() -> None:
    calendar = FixedTradingCalendar({OPEN_DATE})

    with pytest.raises(LookupError, match="no future open date configured"):
        calendar.next_open_date(OPEN_DATE)
