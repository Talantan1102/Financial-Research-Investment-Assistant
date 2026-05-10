"""L0 — MCP tools registration smoke tests.

Verifies that build_server() succeeds and all 6 tools are registered
without requiring any real external services (no tushare / bocha / milvus calls).
"""

from __future__ import annotations

from mcp.server import Server
from mcp.types import Tool


def test_build_server_returns_server_instance() -> None:
    """build_server() must return a mcp.server.Server without raising."""
    from app.mcp_server.server import build_server

    s = build_server()
    assert isinstance(s, Server)


def test_build_server_lists_exactly_6_tools() -> None:
    """The aggregated registry must contain exactly the 6 expected tool names.

    We introspect via s._mcp_tool_registry (attached by build_server() for
    testing) rather than calling the SDK's list_tools() handler directly,
    because the SDK stores the handler as a decorator function — not a coroutine
    — and requires a live MCP session to invoke it through the normal path.
    """
    from app.mcp_server.server import build_server

    s = build_server()
    registry: dict = s._mcp_tool_registry  # type: ignore[attr-defined]
    names = set(registry.keys())
    expected = {
        "get_stock_quote",
        "get_financials",
        "get_news",
        "web_search",
        "kb_search",
        "compare_stocks",
    }
    assert names == expected, f"Expected {expected}, got {names}"


def test_each_tool_module_exports_tool_def_and_handle() -> None:
    """Each of the 6 tool modules exports TOOL_DEF (Tool) and handle (callable)."""
    import importlib

    modules = [
        "app.mcp_server.tools.get_stock_quote",
        "app.mcp_server.tools.get_financials",
        "app.mcp_server.tools.get_news",
        "app.mcp_server.tools.web_search",
        "app.mcp_server.tools.kb_search",
        "app.mcp_server.tools.compare_stocks",
    ]
    for mod_path in modules:
        mod = importlib.import_module(mod_path)
        assert hasattr(mod, "TOOL_DEF"), f"{mod_path} missing TOOL_DEF"
        assert isinstance(mod.TOOL_DEF, Tool), f"{mod_path}.TOOL_DEF not a Tool"
        assert hasattr(mod, "handle"), f"{mod_path} missing handle()"
        assert callable(mod.handle), f"{mod_path}.handle not callable"


def test_tool_def_names_match_expected() -> None:
    """TOOL_DEF.name on each module matches the expected canonical tool name."""
    import importlib

    expected_names = {
        "app.mcp_server.tools.get_stock_quote": "get_stock_quote",
        "app.mcp_server.tools.get_financials": "get_financials",
        "app.mcp_server.tools.get_news": "get_news",
        "app.mcp_server.tools.web_search": "web_search",
        "app.mcp_server.tools.kb_search": "kb_search",
        "app.mcp_server.tools.compare_stocks": "compare_stocks",
    }
    for mod_path, expected_name in expected_names.items():
        mod = importlib.import_module(mod_path)
        assert mod.TOOL_DEF.name == expected_name, (
            f"{mod_path}.TOOL_DEF.name={mod.TOOL_DEF.name!r}, expected {expected_name!r}"
        )
