"""Unit tests for TushareClient — pure transport, no business logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.services.tushare_client import TushareClient, TushareError


@pytest.fixture
def fake_response_ok() -> dict:
    return {
        "request_id": "abc",
        "code": 0,
        "msg": None,
        "data": {
            "fields": ["ts_code", "trade_date", "close"],
            "items": [["600519.SH", "20240501", 1850.0], ["600519.SH", "20240502", 1860.0]],
        },
    }


@pytest.fixture
def fake_response_err() -> dict:
    return {"request_id": "x", "code": 40001, "msg": "token invalid", "data": None}


@pytest.mark.asyncio
async def test_call_returns_dataframe_on_ok(fake_response_ok: dict) -> None:
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json = MagicMock(return_value=fake_response_ok)
    fake_resp.raise_for_status = MagicMock()

    fake_post = AsyncMock(return_value=fake_resp)

    with patch("httpx.AsyncClient.post", fake_post):
        client = TushareClient(token="fake-token")
        df = await client.call("daily", {"ts_code": "600519.SH"})

    assert list(df.columns) == ["ts_code", "trade_date", "close"]
    assert len(df) == 2
    assert df.iloc[0]["close"] == 1850.0


@pytest.mark.asyncio
async def test_call_raises_tushare_error_on_nonzero_code(fake_response_err: dict) -> None:
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json = MagicMock(return_value=fake_response_err)
    fake_resp.raise_for_status = MagicMock()

    fake_post = AsyncMock(return_value=fake_resp)

    with patch("httpx.AsyncClient.post", fake_post):
        client = TushareClient(token="fake-token")
        with pytest.raises(TushareError, match="token invalid"):
            await client.call("daily", {"ts_code": "600519.SH"})


def test_default_base_url_matches_cassette_host() -> None:
    """Cassette host fixture default — feedback_cassette_host_in_match_on memory."""
    client = TushareClient(token="x")
    assert client.base_url == "http://api.tushare.pro"
