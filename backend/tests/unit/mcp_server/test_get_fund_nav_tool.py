"""Unit tests — get_fund_nav tool (pure format function + MCP TOOL_DEF shape)."""

from __future__ import annotations

import pandas as pd
import pytest
from app.tools.get_fund_nav import _format_fund_nav
from app.mcp_server.tools.get_fund_nav import TOOL_DEF


def test_format_fund_nav_latest_and_type() -> None:
    nav = pd.DataFrame({
        "ts_code": ["110011.OF", "110011.OF"],
        "nav_date": ["20261113", "20261114"],
        "unit_nav": [2.500, 2.475],
    })
    out = _format_fund_nav(nav, "110011.OF", fund_type="股票型", fund_name="某白酒主题")
    assert out["fund_type"] == "股票型"
    assert out["latest"]["unit_nav"] == 2.475
    assert out["latest"]["pct_chg"] == pytest.approx((2.475 - 2.500) / 2.500 * 100, rel=1e-6)


def test_format_fund_nav_empty_returns_none_latest() -> None:
    out = _format_fund_nav(pd.DataFrame(), "110011.OF", fund_type=None, fund_name=None)
    assert out["ts_code"] == "110011.OF"
    assert out["latest"] is None


def test_format_fund_nav_has_honesty_note() -> None:
    nav = pd.DataFrame({
        "ts_code": ["110011.OF", "110011.OF"],
        "nav_date": ["20261113", "20261114"],
        "unit_nav": [2.500, 2.475],
    })
    out = _format_fund_nav(nav, "110011.OF", fund_type="股票型", fund_name="某白酒主题")
    assert "as_of_note" in out
    assert "净值" in out["as_of_note"]


def test_tool_def_shape() -> None:
    assert TOOL_DEF.name == "get_fund_nav"
    assert "ts_code" in TOOL_DEF.inputSchema["required"]
    assert "start_date" in TOOL_DEF.inputSchema["required"]
    assert "end_date" in TOOL_DEF.inputSchema["required"]
