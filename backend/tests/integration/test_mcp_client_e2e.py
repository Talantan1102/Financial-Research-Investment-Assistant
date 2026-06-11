"""L1 — launches local MCP server subprocess and exercises tool roundtrip."""

from __future__ import annotations

import pytest
from app.services.mcp_client import MCPClient


@pytest.mark.asyncio
async def test_mcp_client_lists_chat_profile_tools():
    """Boot mcp_server in subprocess; client lists all 9 chat-profile tools."""
    async with MCPClient.from_subprocess() as client:
        tools = await client.list_tools()
        names = {t["name"] for t in tools}
        assert names == {
            "get_stock_quote",
            "get_financial_statements",
            "get_market_indicators",
            "get_corporate_actions",
            "get_news",
            "web_search",
            "kb_search",
            "compare_stocks",
            "get_daily",  # charting: A 股日线时序(K线/走势/归一化/回撤取数)
        }
