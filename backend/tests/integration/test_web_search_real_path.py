"""L1 — WebSearchTool against BochaClient (httpx.MockTransport) with reliability layers.

Verifies the full real path: WebSearchTool.run → BochaClient.search → 200 → normalized items.
Doesn't exercise rate_limiter / circuit_breaker (those have their own L0 tests).
"""

from __future__ import annotations

import json

import httpx
import pytest
from app.services.bocha_client import BochaClient
from app.tools.web_search import WebSearchArgs, WebSearchTool


@pytest.mark.asyncio
async def test_web_search_tool_real_path() -> None:
    captured_query: str = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_query
        body = request.read().decode()
        captured_query = json.loads(body).get("query", "")
        return httpx.Response(
            200,
            json={
                "data": {
                    "webPages": {
                        "value": [
                            {
                                "name": "茅台研报",
                                "url": "https://example.com/r1",
                                "summary": "summary text",
                                "snippet": "snip",
                                "siteName": "site",
                                "datePublished": "2026-04-30",
                            }
                        ]
                    }
                }
            },
        )

    client = BochaClient(api_key="test", transport=httpx.MockTransport(handler))
    tool = WebSearchTool(bocha=client)
    args = WebSearchArgs(query="茅台", search_type="news", count=3)

    result = await tool.run(args)
    n = len(result["items"])
    assert n == 1
    assert result["items"][0]["title"] == "茅台研报"
    # search_type="news" augments query with "最近新闻"
    assert "最近新闻" in captured_query
    await client.aclose()
