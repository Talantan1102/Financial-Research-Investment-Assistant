"""MCP server entry point.

Launched as a subprocess by the FastAPI app's lifespan; exposes 6 chat tools
via stdio transport.  Each tool is a thin adapter around existing tushare /
Bocha / Milvus services (Tasks 14a-14f).

SDK note: mcp.server.Server stores only ONE handler per request type
(list_tools, call_tool).  Per-tool @decorator registration overwrites the
previous handler.  We therefore use an aggregated dispatch pattern:
  - ONE @list_tools() that returns all 6 TOOL_DEFs
  - ONE @call_tool() that dispatches to per-tool handle() by name
Each tool module in app.mcp_server.tools exports TOOL_DEF + handle().
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool registry — maps tool name -> (TOOL_DEF, handle coroutine)
# Populated lazily when build_server() is called so that heavy imports
# (tushare / bocha / milvus) are deferred to runtime.
# ---------------------------------------------------------------------------

_TOOL_MODULES = [
    "app.mcp_server.tools.get_stock_quote",
    "app.mcp_server.tools.get_financials",
    "app.mcp_server.tools.get_news",
    "app.mcp_server.tools.web_search",
    "app.mcp_server.tools.kb_search",
    "app.mcp_server.tools.compare_stocks",
]


def _load_tool_registry() -> dict[str, Any]:
    """Import all tool modules and return {name: module} registry."""
    import importlib

    registry: dict[str, Any] = {}
    for module_path in _TOOL_MODULES:
        mod = importlib.import_module(module_path)
        tool_def: Tool = mod.TOOL_DEF
        registry[tool_def.name] = mod
    return registry


def build_server() -> Server:
    """Construct the MCP server with all 6 tools registered.

    Uses a single @list_tools + single @call_tool to avoid SDK handler
    overwrite issue (only last registered handler survives per request type).

    The loaded tool registry is attached as ``server._mcp_tool_registry``
    (dict mapping tool name -> module) for inspection in tests.
    """
    registry = _load_tool_registry()

    s = Server("financial-research-chat-tools")

    @s.list_tools()
    async def _list_tools() -> list[Tool]:
        return [mod.TOOL_DEF for mod in registry.values()]

    @s.call_tool()
    async def _call_tool(name: str, args: dict[str, Any]) -> list[TextContent]:
        if name not in registry:
            raise ValueError(f"Unknown MCP tool: {name!r}")
        mod = registry[name]
        return await mod.handle(args)

    # Expose registry for test introspection without going through SDK internals.
    s._mcp_tool_registry = registry  # type: ignore[attr-defined]

    return s


async def main() -> None:
    s = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await s.run(read_stream, write_stream, s.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
