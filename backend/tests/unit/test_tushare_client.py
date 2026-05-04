"""Unit tests for TushareClient — pure transport, no business logic.

Uses httpx.MockTransport (matching BochaClient pattern) instead of
patch("httpx.AsyncClient.post"), consistent with persistent client refactor (I-3).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from app.services.tushare_client import TushareClient, TushareError, TushareNetworkError

_OK_PAYLOAD: dict[str, Any] = {
    "request_id": "abc",
    "code": 0,
    "msg": None,
    "data": {
        "fields": ["ts_code", "trade_date", "close"],
        "items": [["600519.SH", "20240501", 1850.0], ["600519.SH", "20240502", 1860.0]],
    },
}

_ERR_PAYLOAD: dict[str, Any] = {
    "request_id": "x",
    "code": 40001,
    "msg": "token invalid",
    "data": None,
}


@pytest.mark.asyncio
async def test_call_returns_dataframe_on_ok() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=_OK_PAYLOAD))
    client = TushareClient(token="fake-token", transport=transport)
    df = await client.call("daily", {"ts_code": "600519.SH"})
    await client.aclose()

    assert list(df.columns) == ["ts_code", "trade_date", "close"]
    assert len(df) == 2
    assert df.iloc[0]["close"] == 1850.0


@pytest.mark.asyncio
async def test_call_raises_tushare_error_on_nonzero_code() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=_ERR_PAYLOAD))
    client = TushareClient(token="fake-token", transport=transport)
    with pytest.raises(TushareError, match="token invalid"):
        await client.call("daily", {"ts_code": "600519.SH"})
    await client.aclose()


def test_default_base_url_matches_cassette_host() -> None:
    """Cassette host fixture default — feedback_cassette_host_in_match_on memory."""
    client = TushareClient(token="x")
    assert client.base_url == "http://api.tushare.pro"


@pytest.mark.asyncio
async def test_call_wraps_connect_error_into_network_error() -> None:
    """I-1: httpx network failures must surface as TushareNetworkError, not raw httpx error."""

    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated DNS failure")

    transport = httpx.MockTransport(handler)
    client = TushareClient(token="fake-token", transport=transport)
    with pytest.raises(TushareNetworkError) as exc_info:
        await client.call("daily", {"ts_code": "600519.SH"})
    await client.aclose()

    # Original exception must be chained
    assert exc_info.value.__cause__ is not None
    assert isinstance(exc_info.value.__cause__, httpx.ConnectError)
    # TushareNetworkError IS-A TushareError
    assert isinstance(exc_info.value, TushareError)
