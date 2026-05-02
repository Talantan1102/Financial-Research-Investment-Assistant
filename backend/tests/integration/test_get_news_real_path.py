"""L1 — GetNewsTool against BochaClient (httpx.MockTransport)."""

from __future__ import annotations

import json

import httpx
import pytest
from app.services.bocha_client import BochaClient
from app.tools.get_news import GetNewsTool, NewsArgs


@pytest.mark.asyncio
async def test_get_news_tool_real_path() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["query"] = json.loads(request.read().decode()).get("query", "")
        return httpx.Response(
            200,
            json={
                "data": {
                    "webPages": {
                        "value": [
                            {
                                "name": "新闻 1",
                                "url": "u",
                                "summary": "s",
                                "snippet": "n",
                                "siteName": "x",
                                "datePublished": "2026-04-30",
                            }
                        ]
                    }
                }
            },
        )

    client = BochaClient(api_key="test", transport=httpx.MockTransport(handler))
    tool = GetNewsTool(bocha=client)

    result = await tool.run(NewsArgs(ts_code="600519.SH", n=3))
    assert "600519.SH" in captured["query"]
    assert "最近新闻" in captured["query"]
    n = len(result["items"])
    assert n == 1
    await client.aclose()
