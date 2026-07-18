from datetime import date, datetime, time
from typing import Protocol
from zoneinfo import ZoneInfo

from app.services.paper_trading.types import MarketPhase

SHANGHAI = ZoneInfo("Asia/Shanghai")


class TradingCalendar(Protocol):
    def is_open_date(self, value: date) -> bool:
        raise NotImplementedError

    def next_open_date(self, value: date) -> date:
        raise NotImplementedError


class FixedTradingCalendar:
    def __init__(self, open_dates: set[date]) -> None:
        self._open_dates = frozenset(open_dates)

    def is_open_date(self, value: date) -> bool:
        return value in self._open_dates

    def next_open_date(self, value: date) -> date:
        later_dates = [open_date for open_date in self._open_dates if open_date > value]
        if not later_dates:
            raise LookupError("no future open date configured")
        return min(later_dates)


class TradingClock:
    def __init__(self, calendar: TradingCalendar) -> None:
        self.calendar = calendar

    def phase(self, now: datetime) -> MarketPhase:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("timezone-aware datetime required")

        local = now.astimezone(SHANGHAI)
        if not self.calendar.is_open_date(local.date()):
            return MarketPhase.CLOSED

        local_time = local.time().replace(tzinfo=None)
        if time(9, 15) <= local_time < time(9, 25):
            return MarketPhase.OPENING_AUCTION
        if time(9, 30) <= local_time < time(11, 30):
            return MarketPhase.MORNING
        if time(11, 30) <= local_time < time(13):
            return MarketPhase.LUNCH
        if time(13) <= local_time < time(14, 57):
            return MarketPhase.AFTERNOON
        if time(14, 57) <= local_time < time(15):
            return MarketPhase.CLOSING_AUCTION
        return MarketPhase.CLOSED
