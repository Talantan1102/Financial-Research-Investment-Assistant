"""Test-only market adapter explicitly included by the paper-trading worker fixture."""

# mypy: disable-error-code="assignment,misc"

from __future__ import annotations

import json
import os
from datetime import datetime

import app.tasks.paper_trading as tasks
from app.services.paper_trading.clock import FixedTradingCalendar
from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.types import RealtimeQuote

fixture_path = os.environ["PAPER_TRADING_WORKER_FIXTURE"]
with open(fixture_path, encoding="utf-8") as stream:
    payload = json.load(stream)

fixed_now = datetime.fromisoformat(str(payload["now"]))
if fixed_now.tzinfo is None or fixed_now.utcoffset() is None:
    raise ValueError("paper trading worker fixture now must be timezone-aware")

open_dates = payload["open_dates"]
if not isinstance(open_dates, list):
    raise ValueError("paper trading worker fixture open_dates must be a list")
fixed_calendar = FixedTradingCalendar(
    {datetime.fromisoformat(str(value)).date() for value in open_dates}
)
fixed_quote = RealtimeQuote.model_validate(payload["quote"], strict=False)


class FixedQuoteProvider:
    async def get(self, ts_code: str) -> RealtimeQuote:
        return self.get_sync(ts_code)

    def get_sync(self, ts_code: str) -> RealtimeQuote:
        if ts_code != fixed_quote.ts_code:
            raise PaperTradingError("quote_unavailable", "fixture quote does not match security")
        return fixed_quote


tasks._now = lambda: fixed_now
tasks._calendar = lambda: fixed_calendar
tasks.TushareRealtimeQuoteProvider = FixedQuoteProvider
