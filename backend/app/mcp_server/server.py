"""MCP server entry point — supports multi-profile (chat_tools / memory).

Plan 4 refactor: accepts --profile argument routing to different tool module
lists. PR #39 default profile = chat_tools (backward compat).

Launched as a subprocess by the FastAPI app's lifespan or by a memory-aware
agent supervisor; exposes chat_tools or memory tools via stdio transport.

SDK note: mcp.server.Server stores only ONE handler per request type
(list_tools, call_tool). Per-tool @decorator registration overwrites the
previous handler. We therefore use an aggregated dispatch pattern:
  - ONE @list_tools() that returns all TOOL_DEFs
  - ONE @call_tool() that dispatches to per-tool handle() by name.
Each tool module exports TOOL_DEF + handle().
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Profile registry
# ---------------------------------------------------------------------------

_CHAT_TOOL_MODULES = [
    "app.mcp_server.tools.get_stock_quote",
    "app.mcp_server.tools.financial_statements",
    "app.mcp_server.tools.market_indicators",
    "app.mcp_server.tools.corporate_actions",
    "app.mcp_server.tools.get_news",
    "app.mcp_server.tools.web_search",
    "app.mcp_server.tools.kb_search",
    "app.mcp_server.tools.compare_stocks",
    "app.mcp_server.tools.get_daily",
    "app.mcp_server.tools.get_index_daily",
    "app.mcp_server.tools.get_fund_nav",
]

_KNOWN_PROFILES = ("chat_tools", "memory")


def _resolve_modules(profile: str) -> list[str]:
    """Return tool module paths for given profile.

    'memory' resolves lazily (from app.mcp_server.tools.memory) so the heavy
    HierarchicalMemory chain isn't imported when running the chat_tools
    subprocess (PR #39 path).
    """
    if profile == "chat_tools":
        return list(_CHAT_TOOL_MODULES)
    if profile == "memory":
        from app.mcp_server.tools.memory import MEMORY_TOOL_MODULES

        return list(MEMORY_TOOL_MODULES)
    raise ValueError(f"unknown profile: {profile!r}")


def _load_tool_registry(profile: str) -> dict[str, Any]:
    """Import all tool modules for given profile and return {name: module}."""
    import importlib

    registry: dict[str, Any] = {}
    for module_path in _resolve_modules(profile):
        mod = importlib.import_module(module_path)
        tool_def: Tool = mod.TOOL_DEF
        registry[tool_def.name] = mod
    return registry


def build_server(profile: str = "chat_tools") -> Server:
    """Construct the MCP server for the given profile.

    Args:
        profile: 'chat_tools' (default, PR #39 backward compat) or 'memory'
            (C.5 Plan 4 ship).

    Returns:
        configured `mcp.server.Server` with `_mcp_tool_registry` attached for
        test introspection.
    """
    registry = _load_tool_registry(profile)
    s = Server(f"financial-research-{profile}")

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
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile",
        default="chat_tools",
        choices=list(_KNOWN_PROFILES),
        help="MCP server profile (chat_tools = PR #39 default; memory = C.5 Plan 4).",
    )
    args = parser.parse_args()

    s = build_server(profile=args.profile)
    async with stdio_server() as (read_stream, write_stream):
        await s.run(read_stream, write_stream, s.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
