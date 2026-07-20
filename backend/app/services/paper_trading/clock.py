from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

import pandas as pd

from app.services.paper_trading.errors import PaperTradingError
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


class TushareTradingCalendar:
    """Synchronous, request-local view over Tushare's SSE trading calendar.

    The injected fetcher keeps transport concerns outside the domain clock. A
    fetched window is cached for the request so confirmation revalidation uses
    the same authoritative snapshot. Missing or malformed exchange data raises
    a stable business error instead of guessing that a weekday is open.
    """

    _LOOKBACK_DAYS = 7
    _LOOKAHEAD_DAYS = 45

    def __init__(self, fetch: Callable[[str, str], pd.DataFrame]) -> None:
        self._fetch = fetch
        self._dates: dict[date, bool] = {}
        self._windows: set[tuple[date, date]] = set()

    def is_open_date(self, value: date) -> bool:
        self._ensure(value)
        return self._dates[value]

    def next_open_date(self, value: date) -> date:
        self._load_window(value)
        candidates = [
            candidate for candidate, is_open in self._dates.items() if candidate > value and is_open
        ]
        if not candidates:
            raise PaperTradingError("trading_calendar_unavailable", "交易日历暂不可用，请稍后重试")
        return min(candidates)

    def _ensure(self, value: date) -> None:
        if value not in self._dates:
            self._load_window(value)
        if value not in self._dates:
            raise PaperTradingError("trading_calendar_unavailable", "交易日历暂不可用，请稍后重试")

    def _load_window(self, anchor: date) -> None:
        start = anchor - timedelta(days=self._LOOKBACK_DAYS)
        end = anchor + timedelta(days=self._LOOKAHEAD_DAYS)
        window = (start, end)
        if window in self._windows:
            return
        try:
            frame = self._fetch(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
            parsed = _parse_tushare_calendar(frame, start=start, end=end)
        except PaperTradingError:
            raise
        except Exception as exc:
            raise PaperTradingError(
                "trading_calendar_unavailable", "交易日历暂不可用，请稍后重试"
            ) from exc
        self._dates.update(parsed)
        self._windows.add(window)


def _parse_tushare_calendar(frame: pd.DataFrame, *, start: date, end: date) -> dict[date, bool]:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise PaperTradingError("trading_calendar_unavailable", "交易日历暂不可用，请稍后重试")
    if not {"cal_date", "is_open"}.issubset(frame.columns):
        raise PaperTradingError("trading_calendar_unavailable", "交易日历暂不可用，请稍后重试")
    parsed: dict[date, bool] = {}
    try:
        for row in frame[["cal_date", "is_open"]].itertuples(index=False):
            calendar_date = datetime.strptime(str(row.cal_date), "%Y%m%d").date()
            raw_open = row.is_open
            if isinstance(raw_open, bool):
                is_open = raw_open
            elif str(raw_open).strip() in {"0", "1"}:
                is_open = str(raw_open).strip() == "1"
            else:
                raise ValueError("invalid is_open value")
            if start <= calendar_date <= end:
                parsed[calendar_date] = is_open
    except (TypeError, ValueError) as exc:
        raise PaperTradingError(
            "trading_calendar_unavailable", "交易日历暂不可用，请稍后重试"
        ) from exc
    if not parsed:
        raise PaperTradingError("trading_calendar_unavailable", "交易日历暂不可用，请稍后重试")
    return parsed


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
