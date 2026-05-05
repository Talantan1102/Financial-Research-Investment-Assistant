"""Unit test for GetBalanceSheetTool (v0.8.5)."""

from __future__ import annotations

import pytest
from app.services.tushare_mock_adapter import LegacyMockTushareAdapter
from app.tools.get_balance_sheet import BalanceSheetArgs, GetBalanceSheetTool
from pydantic import ValidationError


@pytest.mark.asyncio
async def test_get_balance_sheet_returns_solvency_metrics() -> None:
    tool = GetBalanceSheetTool(tushare=LegacyMockTushareAdapter())
    result = await tool.run(BalanceSheetArgs(ts_code="600519.SH"))
    assert result["ts_code"] == "600519.SH"
    # 偿债指标 (派生)
    assert "asset_liability_ratio" in result
    assert "current_ratio" in result
    assert 0 < result["asset_liability_ratio"] < 1
    # 直透 raw 字段
    assert result["total_assets"] > 0
    assert result["total_liab"] > 0


def test_get_balance_sheet_args_validates_ts_code() -> None:
    with pytest.raises(ValidationError):
        BalanceSheetArgs(ts_code=123)  # type: ignore[arg-type]


def test_get_balance_sheet_args_missing_ts_code_rejected() -> None:
    with pytest.raises(ValidationError):
        BalanceSheetArgs()  # type: ignore[call-arg]
