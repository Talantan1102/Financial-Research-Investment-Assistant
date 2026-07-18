import asyncio
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Protocol
from zoneinfo import ZoneInfo

import pandas as pd
from pydantic import ValidationError

from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.types import QuoteLevel, RealtimeQuote

SHANGHAI = ZoneInfo("Asia/Shanghai")
_SOURCE = "tushare.realtime_quote"
_FETCH_FAILURES = (OSError, RuntimeError)


class RealtimeQuoteProvider(Protocol):
    async def get(self, ts_code: str) -> RealtimeQuote:
        raise NotImplementedError


class TushareRealtimeQuoteProvider:
    def __init__(self, fetch: Callable[[str], pd.DataFrame] | None = None) -> None:
        self._fetch = fetch or self._sdk_fetch

    async def get(self, ts_code: str) -> RealtimeQuote:
        try:
            frame = await asyncio.to_thread(self._fetch, ts_code)
        except _FETCH_FAILURES as exc:
            raise PaperTradingError("quote_unavailable", "实时行情暂不可用") from exc

        if not isinstance(frame, pd.DataFrame) or len(frame.index) != 1:
            raise PaperTradingError("quote_unavailable", "实时行情暂不可用")

        try:
            row = self._normalized_row(frame)
            quote = self._map_row(row)
        except (KeyError, TypeError, ValueError, InvalidOperation, ValidationError) as exc:
            raise PaperTradingError("quote_unavailable", "实时行情数据无效") from exc

        if quote.ts_code != ts_code:
            raise PaperTradingError("quote_unavailable", "实时行情证券代码不匹配")
        return quote

    def assert_fresh(self, quote: RealtimeQuote, now: datetime, max_age_seconds: int) -> None:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if (
            isinstance(max_age_seconds, bool)
            or not isinstance(max_age_seconds, int)
            or max_age_seconds <= 0
        ):
            raise ValueError("max_age_seconds must be a positive integer")

        age = abs(now.astimezone(SHANGHAI) - quote.quoted_at.astimezone(SHANGHAI))
        if age > timedelta(seconds=max_age_seconds):
            raise PaperTradingError("stale_quote", "实时行情已过期")

    @staticmethod
    def _sdk_fetch(ts_code: str) -> pd.DataFrame:
        import tushare

        return tushare.realtime_quote(ts_code=ts_code)

    @staticmethod
    def _normalized_row(frame: pd.DataFrame) -> Mapping[str, object]:
        columns = [str(column).upper() for column in frame.columns]
        if len(set(columns)) != len(columns):
            raise ValueError("duplicate fields after case normalization")
        return dict(zip(columns, frame.iloc[0].tolist(), strict=True))

    @classmethod
    def _map_row(cls, row: Mapping[str, object]) -> RealtimeQuote:
        quoted_at = cls._parse_timestamp(row["DATE"], row["TIME"])
        bids = tuple(
            QuoteLevel(
                price=cls._positive_decimal(row[f"BID{level}"]),
                quantity=cls._nonnegative_integer(row[f"BID_VOL{level}"]),
            )
            for level in range(1, 6)
        )
        asks = tuple(
            QuoteLevel(
                price=cls._positive_decimal(row[f"ASK{level}"]),
                quantity=cls._nonnegative_integer(row[f"ASK_VOL{level}"]),
            )
            for level in range(1, 6)
        )
        ts_code = str(row["TS_CODE"]).strip()
        name = str(row["NAME"]).strip()
        if not ts_code or not name:
            raise ValueError("security identity is empty")
        return RealtimeQuote(
            ts_code=ts_code,
            name=name,
            quoted_at=quoted_at,
            previous_close=cls._positive_decimal(row["PRE_CLOSE"]),
            last_price=cls._positive_decimal(row["PRICE"]),
            bids=bids,
            asks=asks,
            source=_SOURCE,
            suspended=False,
        )

    @staticmethod
    def _parse_timestamp(date_value: object, time_value: object) -> datetime:
        date_text = str(date_value).strip()
        time_text = str(time_value).strip()
        for date_format in ("%Y%m%d", "%Y-%m-%d"):
            try:
                quote_date = datetime.strptime(date_text, date_format).date()
                quote_time = datetime.fromisoformat(f"2000-01-01T{time_text}").time()
                if quote_time.tzinfo is not None:
                    raise ValueError("quote time must not contain a timezone")
                return datetime.combine(quote_date, quote_time, tzinfo=SHANGHAI)
            except ValueError:
                continue
        raise ValueError("invalid quote timestamp")

    @staticmethod
    def _positive_decimal(value: object) -> Decimal:
        number = Decimal(str(value).strip())
        if not number.is_finite() or number <= 0:
            raise ValueError("expected a finite positive decimal")
        return number

    @staticmethod
    def _nonnegative_integer(value: object) -> int:
        number = Decimal(str(value).strip())
        if not number.is_finite() or number < 0 or number != number.to_integral_value():
            raise ValueError("expected a finite nonnegative integer")
        return int(number)
