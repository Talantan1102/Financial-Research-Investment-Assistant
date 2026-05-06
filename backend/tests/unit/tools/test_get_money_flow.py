"""Unit test for GetMoneyFlowTool (v0.8.5)."""

from __future__ import annotations

from typing import cast

import pandas as pd
import pytest
from app.services.tushare_mock_adapter import LegacyMockTushareAdapter
from app.services.tushare_service import TushareService
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


@pytest.mark.asyncio
async def test_classify_outflow() -> None:
    """sell_lg=3e8 > buy_lg=1e8 → 'outflow' (binary classifier 反向覆盖)."""

    class _StubTushare:
        def __init__(self, df: pd.DataFrame) -> None:
            self._df = df

        async def get_money_flow(
            self, *, ts_code: str, start_date: str, end_date: str
        ) -> pd.DataFrame:
            return self._df

    df = pd.DataFrame(
        {
            "ts_code": ["600519.SH"],
            "trade_date": ["20241231"],
            "buy_lg_amount": [1e8],
            "sell_lg_amount": [3e8],
            "buy_md_amount": [1e8],
            "sell_md_amount": [1e8],
        }
    )
    tool = GetMoneyFlowTool(tushare=cast(TushareService, _StubTushare(df)))
    result = await tool.run(
        MoneyFlowArgs(ts_code="600519.SH", start_date="20241201", end_date="20241231")
    )
    assert result["net_lg_signal"] == "outflow"
