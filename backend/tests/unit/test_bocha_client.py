"""L0 — BochaClient HTTP request shape + 5-class error mapping."""

import json
from typing import Any

import httpx
import pytest
from app.services.bocha_client import BochaClient
from app.services.bocha_errors import (
    BochaAuthError,
    BochaClientError,
    BochaNetworkError,
    BochaRateLimitError,
    BochaServerError,
)


def _ok_response(payload: dict[str, Any] | None = None) -> httpx.Response:
    body = payload or {
        "data": {
            "webPages": {
                "value": [
                    {
                        "name": "茅台",
                        "url": "https://example.com/maotai",
                        "summary": "贵州茅台股价 1820 元",
                        "snippet": "片段",
                        "siteName": "示例",
                        "datePublished": "2026-04-30",
                    },
                ],
            },
        },
    }
    return httpx.Response(200, json=body)


@pytest.mark.asyncio
async def test_search_request_shape() -> None:
    """Verifies POST URL + auth header + body shape."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization", "")
        captured["body"] = request.read().decode()
        return _ok_response()

    transport = httpx.MockTransport(handler)
    client = BochaClient(api_key="test-key", transport=transport)
    result = await client.search(query="茅台", count=3)
    await client.aclose()

    body = json.loads(captured["body"])
    assert captured["url"] == "https://api.bochaai.com/v1/web-search"
    assert captured["auth"] == "Bearer test-key"
    assert "query" in body
    assert body["count"] == 3
    n = len(result["items"])
    assert n == 1
    assert result["items"][0]["title"] == "茅台"


@pytest.mark.asyncio
async def test_search_429_raises_rate_limit() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(429, json={"error": "rate limit"}))
    client = BochaClient(api_key="k", transport=transport)
    with pytest.raises(BochaRateLimitError):
        await client.search(query="x", count=1)
    await client.aclose()


@pytest.mark.asyncio
async def test_search_401_raises_auth() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(401, json={"error": "unauthorized"}))
    client = BochaClient(api_key="k", transport=transport)
    with pytest.raises(BochaAuthError):
        await client.search(query="x", count=1)
    await client.aclose()


@pytest.mark.asyncio
async def test_search_403_raises_auth() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(403, json={}))
    client = BochaClient(api_key="k", transport=transport)
    with pytest.raises(BochaAuthError):
        await client.search(query="x", count=1)
    await client.aclose()


@pytest.mark.asyncio
async def test_search_500_raises_server() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(500, json={"error": "server"}))
    client = BochaClient(api_key="k", transport=transport)
    with pytest.raises(BochaServerError):
        await client.search(query="x", count=1)
    await client.aclose()


@pytest.mark.asyncio
async def test_search_400_raises_client() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(400, json={"error": "bad request"}))
    client = BochaClient(api_key="k", transport=transport)
    with pytest.raises(BochaClientError):
        await client.search(query="x", count=1)
    await client.aclose()


@pytest.mark.asyncio
async def test_search_network_error_raises_network() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failure")

    transport = httpx.MockTransport(handler)
    client = BochaClient(api_key="k", transport=transport)
    with pytest.raises(BochaNetworkError):
        await client.search(query="x", count=1)
    await client.aclose()


@pytest.mark.asyncio
async def test_search_returns_normalized_items() -> None:
    """All response fields normalized to consistent keys."""
    transport = httpx.MockTransport(lambda req: _ok_response())
    client = BochaClient(api_key="k", transport=transport)
    result = await client.search(query="x", count=1)
    item = result["items"][0]
    assert "title" in item
    assert "url" in item
    assert "summary" in item
    assert "snippet" in item
    assert "site_name" in item
    assert "date" in item
    await client.aclose()
