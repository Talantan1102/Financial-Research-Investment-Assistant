"""L0 — get_sector_daily 纯函数 + TOOL_DEF 形状单测(不碰网络)。"""

from __future__ import annotations

from app.mcp_server.tools.get_sector_daily import TOOL_DEF
from app.tools.get_sector_daily import _format_sector


def test_format_sector_returns_industry_and_pct() -> None:
    out = _format_sector(industry="白酒", index_code="801120.SI", pct_chg=-3.0)
    assert out["industry"] == "白酒"
    assert out["pct_chg"] == -3.0
    assert out["index_code"] == "801120.SI"
    assert "note" not in out


def test_format_sector_unmapped_industry_returns_none_pct_and_note() -> None:
    out = _format_sector(industry="火星概念", index_code=None, pct_chg=None)
    assert out["industry"] == "火星概念"
    assert out["pct_chg"] is None
    assert out["index_code"] is None
    assert out.get("note") == "该行业指数未配置"


def test_tool_def_shape() -> None:
    assert TOOL_DEF.name == "get_sector_daily"
    assert "ts_code" in TOOL_DEF.inputSchema["required"]
    assert "trade_date" in TOOL_DEF.inputSchema["required"]
