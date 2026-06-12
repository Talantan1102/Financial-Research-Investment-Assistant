"""Unit tests for Position.asset_class field — pure Python object, no DB.

TDD Step 1: these tests must FAIL before the column is added to Position.
"""

from __future__ import annotations

from app.models.position import Position


def test_position_asset_class_defaults_to_stock() -> None:
    p = Position(id="x", ts_code="600519.SH", name="贵州茅台", quantity=100)
    assert p.asset_class == "stock"


def test_position_asset_class_accepts_fund() -> None:
    p = Position(id="y", ts_code="110011.OF", name="某基金", quantity=0, asset_class="fund_otc")
    assert p.asset_class == "fund_otc"
