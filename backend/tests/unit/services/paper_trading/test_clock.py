from datetime import date, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from app.services.paper_trading.clock import (
    FixedTradingCalendar,
    TradingClock,
    TushareTradingCalendar,
)
from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.types import MarketPhase
from app.services.trade_calendar import build_calendar_df

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

    assert clock.phase(datetime(2026, 7, 20, 10, 0, tzinfo=SHANGHAI)) == (MarketPhase.MORNING)
    assert clock.phase(datetime(2026, 7, 20, 9, 20, tzinfo=SHANGHAI)) == (
        MarketPhase.OPENING_AUCTION
    )
    assert clock.phase(datetime(2026, 7, 20, 12, 0, tzinfo=SHANGHAI)) == (MarketPhase.LUNCH)
    assert clock.phase(datetime(2026, 7, 20, 14, 58, tzinfo=SHANGHAI)) == (
        MarketPhase.CLOSING_AUCTION
    )
    assert clock.phase(datetime(2026, 7, 20, 15, 1, tzinfo=SHANGHAI)) == (MarketPhase.CLOSED)
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

    assert _clock().phase(datetime(2026, 7, 20, hour, minute, second, tzinfo=SHANGHAI)) == expected


def test_non_open_date_is_closed() -> None:
    assert _clock().phase(datetime(2026, 7, 21, 10, 0, tzinfo=SHANGHAI)) == (MarketPhase.CLOSED)


def test_phase_converts_non_shanghai_timezone() -> None:
    assert _clock().phase(datetime(2026, 7, 20, 2, 0, tzinfo=UTC)) == (MarketPhase.MORNING)


def test_phase_converts_previous_local_date_to_open_shanghai_date() -> None:
    assert _clock().phase(datetime(2026, 7, 19, 18, 30, tzinfo=LOS_ANGELES)) == MarketPhase.MORNING


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


def test_tushare_calendar_uses_exchange_rows_instead_of_weekdays() -> None:
    calls = 0

    def fetch(start: str, end: str) -> pd.DataFrame:
        nonlocal calls
        calls += 1
        assert start <= "20261001" <= end
        return build_calendar_df(start, end)

    calendar = TushareTradingCalendar(fetch)

    assert not calendar.is_open_date(date(2026, 10, 1))
    assert calendar.next_open_date(date(2026, 10, 1)) == date(2026, 10, 9)
    assert calls == 1


@pytest.mark.parametrize(
    "frame",
    [
        pd.DataFrame(),
        pd.DataFrame([{"cal_date": "20261001", "is_open": "unknown"}]),
    ],
)
def test_tushare_calendar_fails_closed_for_missing_or_invalid_data(frame: pd.DataFrame) -> None:
    calendar = TushareTradingCalendar(lambda _start, _end: frame)

    with pytest.raises(PaperTradingError, match="交易日历") as caught:
        calendar.is_open_date(date(2026, 10, 1))

    assert caught.value.code == "trading_calendar_unavailable"


@pytest.mark.parametrize("gap", ["start", "anchor", "middle", "end"])
def test_tushare_calendar_rejects_any_missing_day_in_fetched_window(gap: str) -> None:
    anchor = date(2026, 10, 1)

    def fetch(start: str, end: str) -> pd.DataFrame:
        frame = build_calendar_df(start, end)
        if gap == "start":
            missing = start
        elif gap == "anchor":
            missing = anchor.strftime("%Y%m%d")
        elif gap == "middle":
            missing = (anchor + timedelta(days=10)).strftime("%Y%m%d")
        else:
            missing = end
        return frame.loc[frame["cal_date"] != missing].reset_index(drop=True)

    calendar = TushareTradingCalendar(fetch)

    with pytest.raises(PaperTradingError) as caught:
        calendar.is_open_date(anchor)

    assert caught.value.code == "trading_calendar_unavailable"


@pytest.mark.parametrize("duplicate_value", [0, 1])
def test_tushare_calendar_rejects_duplicate_calendar_dates(duplicate_value: int) -> None:
    anchor = date(2026, 10, 1)

    def fetch(start: str, end: str) -> pd.DataFrame:
        frame = build_calendar_df(start, end)
        duplicate = pd.DataFrame(
            [{"cal_date": anchor.strftime("%Y%m%d"), "is_open": duplicate_value}]
        )
        return pd.concat([frame, duplicate], ignore_index=True)

    with pytest.raises(PaperTradingError) as caught:
        TushareTradingCalendar(fetch).is_open_date(anchor)

    assert caught.value.code == "trading_calendar_unavailable"


def test_tushare_calendar_accepts_complete_unsorted_response_with_out_of_range_rows() -> None:
    anchor = date(2026, 10, 1)

    def fetch(start: str, end: str) -> pd.DataFrame:
        frame = build_calendar_df(start, end).sample(frac=1, random_state=7)
        outside = pd.DataFrame([{"cal_date": "20200101", "is_open": 0}])
        return pd.concat([outside, frame], ignore_index=True)

    calendar = TushareTradingCalendar(fetch)

    assert not calendar.is_open_date(anchor)
    assert calendar.next_open_date(anchor) == date(2026, 10, 9)
