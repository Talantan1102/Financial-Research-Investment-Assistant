"""L0 — server.build_server(profile=...) routes to correct tool registry.

Plan 4: refactor MCP server.py to support --profile (chat_tools / memory).
PR #39 default profile = chat_tools (backward compat).
"""

from __future__ import annotations

import pytest


def test_chat_tools_profile_has_nine_tools() -> None:
    from app.mcp_server.server import build_server

    s = build_server(profile="chat_tools")
    names = set(s._mcp_tool_registry)  # type: ignore[attr-defined]
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


def test_memory_profile_has_six_memory_tools() -> None:
    from app.mcp_server.server import build_server

    s = build_server(profile="memory")
    names = set(s._mcp_tool_registry)  # type: ignore[attr-defined]
    assert names == {
        "core_memory_append",
        "core_memory_replace",
        "archival_memory_insert",
        "archival_memory_search",
        "archival_memory_traverse",
        "recall_memory_search",
    }


def test_unknown_profile_raises() -> None:
    from app.mcp_server.server import build_server

    with pytest.raises(ValueError, match="unknown profile"):
        build_server(profile="bogus")


def test_default_profile_is_chat_tools_for_backward_compat() -> None:
    """No --profile arg → chat_tools (PR #39 backward compat)."""
    from app.mcp_server.server import build_server

    s = build_server()
    # Default profile must be chat_tools — PR #39 e2e tests rely on this.
    assert "get_stock_quote" in s._mcp_tool_registry  # type: ignore[attr-defined]


def test_mcp_servers_yaml_exists() -> None:
    """mcp_servers.yaml at repo root lists both profiles."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    yaml_path = repo_root / "mcp_servers.yaml"
    assert yaml_path.exists(), f"missing: {yaml_path}"
    content = yaml_path.read_text(encoding="utf-8")
    assert "chat_tools" in content
    assert "memory" in content
