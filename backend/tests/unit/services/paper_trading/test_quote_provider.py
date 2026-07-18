import asyncio
import threading
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.quote_provider import TushareRealtimeQuoteProvider

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _quote_row(**changes: Any) -> dict[str, object]:
    row: dict[str, object] = {
        "TS_CODE": "600519.SH",
        "NAME": "贵州茅台",
        "DATE": "20260720",
        "TIME": "10:00:00",
        "PRE_CLOSE": "1500",
        "PRICE": "1501",
    }
    for level in range(1, 6):
        row[f"B{level}_P"] = str(1501 - level)
        row[f"B{level}_V"] = str(level * 100)
        row[f"A{level}_P"] = str(1501 + level)
        row[f"A{level}_V"] = str(level * 200)
    row.update(changes)
    return row


def test_get_sync_maps_quote_on_calling_thread() -> None:
    calling_thread = threading.get_ident()
    fetch_thread: int | None = None

    def fetch(ts_code: str) -> pd.DataFrame:
        nonlocal fetch_thread
        assert ts_code == "600519.SH"
        fetch_thread = threading.get_ident()
        return pd.DataFrame([_quote_row()])

    quote = TushareRealtimeQuoteProvider(fetch=fetch).get_sync("600519.SH")

    assert fetch_thread == calling_thread
    assert quote.ts_code == "600519.SH"
    assert quote.asks[0].price == Decimal("1502")


@pytest.mark.asyncio
async def test_maps_exactly_five_levels_on_a_worker_thread() -> None:
    calling_thread = threading.get_ident()
    fetch_thread: int | None = None

    def fetch(ts_code: str) -> pd.DataFrame:
        nonlocal fetch_thread
        assert ts_code == "600519.SH"
        fetch_thread = threading.get_ident()
        return pd.DataFrame([_quote_row()])

    quote = await TushareRealtimeQuoteProvider(fetch=fetch).get("600519.SH")

    assert fetch_thread is not None and fetch_thread != calling_thread
    assert quote.ts_code == "600519.SH"
    assert quote.name == "贵州茅台"
    assert quote.quoted_at == datetime(2026, 7, 20, 10, tzinfo=SHANGHAI)
    assert quote.previous_close == Decimal("1500")
    assert quote.last_price == Decimal("1501")
    assert quote.bids[0].price == Decimal("1500")
    assert quote.bids[4].quantity == 500
    assert quote.asks[0].price == Decimal("1502")
    assert quote.asks[4].quantity == 1000
    assert quote.source == "tushare.realtime_quote"
    assert quote.suspended is False


@pytest.mark.asyncio
async def test_maps_columns_without_depending_on_column_case() -> None:
    lower_row = {key.lower(): value for key, value in _quote_row().items()}
    quote = await TushareRealtimeQuoteProvider(fetch=lambda _: pd.DataFrame([lower_row])).get(
        "600519.SH"
    )
    assert quote.ts_code == "600519.SH"
    assert len(quote.bids) == len(quote.asks) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "frame",
    [
        pd.DataFrame(),
        pd.DataFrame([_quote_row(), _quote_row()]),
        pd.DataFrame([_quote_row(TS_CODE="000001.SZ")]),
        pd.DataFrame([{key: value for key, value in _quote_row().items() if key != "A5_P"}]),
    ],
    ids=["empty", "multiple rows", "wrong symbol", "missing field"],
)
async def test_rejects_ambiguous_or_malformed_responses(frame: pd.DataFrame) -> None:
    provider = TushareRealtimeQuoteProvider(fetch=lambda _: frame)
    with pytest.raises(PaperTradingError) as caught:
        await provider.get("600519.SH")
    assert caught.value.code == "quote_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("PRICE", "0"),
        ("PRE_CLOSE", "-1"),
        ("B1_P", "nan"),
        ("A2_V", "inf"),
        ("B3_V", "-1"),
        ("A4_V", "1.5"),
        ("DATE", "not-a-date"),
        ("TIME", "25:00:00"),
    ],
)
async def test_rejects_invalid_field_values(field: str, value: str) -> None:
    provider = TushareRealtimeQuoteProvider(
        fetch=lambda _: pd.DataFrame([_quote_row(**{field: value})])
    )
    with pytest.raises(PaperTradingError) as caught:
        await provider.get("600519.SH")
    assert caught.value.code == "quote_unavailable"


@pytest.mark.asyncio
async def test_normalizes_operational_fetch_failures() -> None:
    def unavailable(_: str) -> pd.DataFrame:
        raise ConnectionError("network down")

    with pytest.raises(PaperTradingError) as caught:
        await TushareRealtimeQuoteProvider(fetch=unavailable).get("600519.SH")
    assert caught.value.code == "quote_unavailable"
    assert isinstance(caught.value.__cause__, ConnectionError)


@pytest.mark.asyncio
async def test_does_not_hide_programmer_errors_or_cancellation() -> None:
    def broken(_: str) -> pd.DataFrame:
        raise TypeError("bad adapter")

    with pytest.raises(TypeError, match="bad adapter"):
        await TushareRealtimeQuoteProvider(fetch=broken).get("600519.SH")

    started = threading.Event()
    release = threading.Event()

    def blocking(_: str) -> pd.DataFrame:
        started.set()
        release.wait(timeout=2)
        return pd.DataFrame([_quote_row()])

    task = asyncio.create_task(TushareRealtimeQuoteProvider(fetch=blocking).get("600519.SH"))
    await asyncio.to_thread(started.wait, 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()


def test_assert_fresh_accepts_boundary_and_rejects_past_or_future_staleness() -> None:
    quote_time = datetime(2026, 7, 20, 10, tzinfo=SHANGHAI)
    provider = TushareRealtimeQuoteProvider(fetch=lambda _: pd.DataFrame())
    quote = asyncio.run(
        TushareRealtimeQuoteProvider(fetch=lambda _: pd.DataFrame([_quote_row()])).get("600519.SH")
    )

    provider.assert_fresh(quote, quote_time + timedelta(seconds=15), 15)
    for now in (
        quote_time + timedelta(seconds=16),
        quote_time - timedelta(seconds=16),
    ):
        with pytest.raises(PaperTradingError) as caught:
            provider.assert_fresh(quote, now, 15)
        assert caught.value.code == "stale_quote"


@pytest.mark.parametrize(
    ("now", "max_age"),
    [
        (datetime(2026, 7, 20, 10), 15),
        (datetime(2026, 7, 20, 10, tzinfo=SHANGHAI), 0),
        (datetime(2026, 7, 20, 10, tzinfo=SHANGHAI), -1),
        (datetime(2026, 7, 20, 10, tzinfo=SHANGHAI), True),
    ],
)
def test_assert_fresh_rejects_invalid_inputs(now: datetime, max_age: int) -> None:
    quote = asyncio.run(
        TushareRealtimeQuoteProvider(fetch=lambda _: pd.DataFrame([_quote_row()])).get("600519.SH")
    )
    with pytest.raises(ValueError):
        TushareRealtimeQuoteProvider(fetch=lambda _: pd.DataFrame()).assert_fresh(
            quote, now, max_age
        )


@pytest.mark.asyncio
async def test_default_adapter_calls_tushare_realtime_quote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def realtime_quote(*, ts_code: str) -> pd.DataFrame:
        calls.append(ts_code)
        return pd.DataFrame([_quote_row()])

    monkeypatch.setattr("tushare.realtime_quote", realtime_quote)
    quote = await TushareRealtimeQuoteProvider().get("600519.SH")
    assert calls == ["600519.SH"]
    assert quote.ts_code == "600519.SH"


@pytest.mark.asyncio
async def test_normalizes_requested_ts_code_before_fetch() -> None:
    calls: list[str] = []

    def fetch(ts_code: str) -> pd.DataFrame:
        calls.append(ts_code)
        return pd.DataFrame([_quote_row()])

    quote = await TushareRealtimeQuoteProvider(fetch=fetch).get(" 600519.sh ")
    assert calls == ["600519.SH"]
    assert quote.ts_code == "600519.SH"


@pytest.mark.asyncio
@pytest.mark.parametrize("ts_code", ["", "600519", "ABC519.SH", "600519.BJ", "600519.SH,000001.SZ"])
async def test_rejects_invalid_requested_ts_code_without_fetching(ts_code: str) -> None:
    called = False

    def fetch(_: str) -> pd.DataFrame:
        nonlocal called
        called = True
        return pd.DataFrame([_quote_row()])

    with pytest.raises(PaperTradingError) as caught:
        await TushareRealtimeQuoteProvider(fetch=fetch).get(ts_code)
    assert caught.value.code == "quote_unavailable"
    assert called is False


@pytest.mark.asyncio
async def test_recognizes_tushare_suspended_security_shape() -> None:
    suspended_fields = {"PRICE": "0"}
    for level in range(1, 6):
        suspended_fields[f"B{level}_P"] = "0"
        suspended_fields[f"B{level}_V"] = "0"
        suspended_fields[f"A{level}_P"] = "0"
        suspended_fields[f"A{level}_V"] = "0"

    provider = TushareRealtimeQuoteProvider(
        fetch=lambda _: pd.DataFrame([_quote_row(**suspended_fields)])
    )
    with pytest.raises(PaperTradingError) as caught:
        await provider.get("600519.SH")
    assert caught.value.code == "suspended_security"


@pytest.mark.asyncio
async def test_partial_zero_book_is_malformed_not_suspended() -> None:
    provider = TushareRealtimeQuoteProvider(
        fetch=lambda _: pd.DataFrame([_quote_row(PRICE="0", B1_P="0")])
    )
    with pytest.raises(PaperTradingError) as caught:
        await provider.get("600519.SH")
    assert caught.value.code == "quote_unavailable"
