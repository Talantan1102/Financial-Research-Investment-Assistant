"""L0 — MCP tools registration smoke tests.

Verifies that build_server() succeeds and all 8 chat-profile tools are
registered without requiring any real external services (no tushare /
bocha / milvus calls).
"""

from __future__ import annotations

from mcp.server import Server
from mcp.types import Tool


def test_build_server_returns_server_instance() -> None:
    """build_server() must return a mcp.server.Server without raising."""
    from app.mcp_server.server import build_server

    s = build_server()
    assert isinstance(s, Server)


def test_build_server_lists_exactly_12_tools() -> None:
    """The aggregated registry must contain exactly the 12 expected tool names.

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
        "get_financial_statements",
        "get_market_indicators",
        "get_corporate_actions",
        "get_news",
        "web_search",
        "kb_search",
        "compare_stocks",
        "get_daily",
        "get_index_daily",
        "get_fund_nav",
        "get_sector_daily",
    }
    assert names == expected, f"Expected {expected}, got {names}"


def test_each_tool_module_exports_tool_def_and_handle() -> None:
    """Each of the 12 chat-profile tool modules exports TOOL_DEF + handle()."""
    import importlib

    modules = [
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
        "app.mcp_server.tools.get_sector_daily",
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
        "app.mcp_server.tools.financial_statements": "get_financial_statements",
        "app.mcp_server.tools.market_indicators": "get_market_indicators",
        "app.mcp_server.tools.corporate_actions": "get_corporate_actions",
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


# C75: orphan MCP adapter get_financials.py was deleted — financial_statements
# (statement='income') already covers GetFinancialsTool.  These two guards
# prevent accidental re-introduction and confirm the income path still exists.


def test_orphan_mcp_get_financials_adapter_is_deleted() -> None:
    """C75: app.mcp_server.tools.get_financials must NOT exist (deleted orphan).

    The module was never registered in _CHAT_TOOL_MODULES and duplicated the
    'income' branch of financial_statements.py — SSOT violation.
    """
    import importlib

    import pytest

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.mcp_server.tools.get_financials")


def test_financial_statements_income_path_uses_get_financials_tool() -> None:
    """C75: financial_statements.py statement='income' still dispatches to GetFinancialsTool.

    Confirms the only registered income path is intact after the orphan deletion.
    """
    import importlib
    import inspect

    mod = importlib.import_module("app.mcp_server.tools.financial_statements")
    source = inspect.getsource(mod.handle)
    assert "GetFinancialsTool" in source, (
        "financial_statements.handle must still import GetFinancialsTool for income path"
    )
    assert 'statement == "income"' in source, (
        "financial_statements.handle must still have an income branch"
    )
