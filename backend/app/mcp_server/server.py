"""MCP server entry point.

Launched as a subprocess by the FastAPI app's lifespan; exposes 6 chat tools
via stdio transport.  Each tool is a thin adapter around existing tushare /
Bocha / Milvus services (Tasks 14a-14f).
"""

from __future__ import annotations

import asyncio
import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server

logger = logging.getLogger(__name__)


def build_server() -> Server:
    """Construct the MCP server with all 6 tools registered."""
    from app.mcp_server.tools.compare_stocks import register as register_compare
    from app.mcp_server.tools.get_financials import register as register_financials
    from app.mcp_server.tools.get_news import register as register_news
    from app.mcp_server.tools.get_stock_quote import register as register_quote
    from app.mcp_server.tools.kb_search import register as register_kb
    from app.mcp_server.tools.web_search import register as register_web

    s = Server("financial-research-chat-tools")
    register_quote(s)
    register_financials(s)
    register_news(s)
    register_web(s)
    register_kb(s)
    register_compare(s)
    return s


async def main() -> None:
    s = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await s.run(read_stream, write_stream, s.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
