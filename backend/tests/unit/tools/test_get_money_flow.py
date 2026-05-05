"""Unit test for GetMoneyFlowTool (v0.8.5)."""

from __future__ import annotations

import pytest
from app.services.tushare_mock_adapter import LegacyMockTushareAdapter
from app.tools.get_money_flow import GetMoneyFlowTool, MoneyFlowArgs
from pydantic import ValidationError


@pytest.mark.asyncio
async def test_get_money_flow_returns_inflow_signal() -> None:
    """Mock fixture: buy_lg=3.5e8 > sell_lg=3.2e8 → 'inflow'."""
    tool = GetMoneyFlowTool(tushare=LegacyMockTushareAdapter())
    result = await tool.run(
        MoneyFlowArgs(ts_code="600519.SH", start_date="20241201", end_date="20241231")
    )
    assert result["ts_code"] == "600519.SH"
    assert result["buy_lg_amount"] > 0
    assert result["sell_lg_amount"] > 0
    assert result["net_lg_signal"] == "inflow"


def test_get_money_flow_args_required_dates() -> None:
    """start_date / end_date 是必填字段."""
    with pytest.raises(ValidationError):
        MoneyFlowArgs(ts_code="600519.SH")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        MoneyFlowArgs(ts_code="600519.SH", start_date="20241201")  # type: ignore[call-arg]
