"""Unit tests for TushareCache — sqlite-based cache with TTL."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pandas as pd
import pytest
from app.services.tushare_cache import TushareCache, classify_ttl


@pytest.fixture
def cache(tmp_path: Path) -> TushareCache:
    return TushareCache(db_path=tmp_path / "cache.sqlite")


@pytest.mark.asyncio
async def test_set_then_get_hits(cache: TushareCache) -> None:
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    await cache.set("daily", {"ts_code": "600519.SH"}, df, ttl_s=60)
    got = await cache.get("daily", {"ts_code": "600519.SH"})
    assert got is not None
    pd.testing.assert_frame_equal(got, df)


@pytest.mark.asyncio
async def test_get_returns_none_on_miss(cache: TushareCache) -> None:
    got = await cache.get("daily", {"ts_code": "000001.SZ"})
    assert got is None


@pytest.mark.asyncio
async def test_get_returns_none_on_expired(cache: TushareCache) -> None:
    df = pd.DataFrame({"a": [1]})
    await cache.set("anns", {"ts_code": "x"}, df, ttl_s=0.01)
    await asyncio.sleep(0.05)
    got = await cache.get("anns", {"ts_code": "x"})
    assert got is None


def test_classify_ttl_financial() -> None:
    assert classify_ttl("income") == 365 * 24 * 3600  # 永久(用 1 年代表)
    # Tushare Pro balance sheet API is "balancesheet" (no underscore)
    assert classify_ttl("balancesheet") == 365 * 24 * 3600
    assert classify_ttl("cashflow") == 365 * 24 * 3600
    assert classify_ttl("fina_indicator") == 365 * 24 * 3600
    assert classify_ttl("stk_holdernumber") == 365 * 24 * 3600


def test_classify_ttl_announcements() -> None:
    # Tushare Pro daily announcements API is "anns_d" (not "anns")
    assert classify_ttl("anns_d") == 24 * 3600
    assert classify_ttl("disclosure_date") == 24 * 3600


def test_classify_ttl_daily() -> None:
    assert classify_ttl("daily") == 3600  # 1h(简化版,spec 写"当日 16:00",这里用 1h cache 起步)


def test_classify_ttl_default() -> None:
    assert classify_ttl("unknown_api") == 3600


@pytest.mark.asyncio
async def test_get_returns_none_on_corrupt_blob(cache: TushareCache) -> None:
    """Cache miss invariant: corrupt blob must return None, not raise."""
    import sqlite3 as _sqlite3

    # Initialise the schema by writing a real entry first, then overwrite its blob
    df = pd.DataFrame({"a": [1]})
    await cache.set("daily", {"ts_code": "x"}, df, ttl_s=3600)

    # Overwrite the stored blob with garbage bytes
    with _sqlite3.connect(cache._db_path) as conn:
        conn.execute(
            "UPDATE tushare_cache SET response_blob = ? WHERE api_name = 'daily'",
            (b"not-a-valid-pickle-blob",),
        )

    result = await cache.get("daily", {"ts_code": "x"})
    assert result is None
