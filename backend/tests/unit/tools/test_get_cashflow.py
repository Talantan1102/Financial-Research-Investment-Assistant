"""Unit test for GetCashflowTool (v0.8.5)."""

from __future__ import annotations

from typing import cast

import pandas as pd
import pytest
from app.services.tushare_mock_adapter import LegacyMockTushareAdapter
from app.services.tushare_service import TushareService
from app.tools.get_cashflow import CashflowArgs, GetCashflowTool
from pydantic import ValidationError


@pytest.mark.asyncio
async def test_get_cashflow_returns_ocf_and_signal() -> None:
    tool = GetCashflowTool(tushare=LegacyMockTushareAdapter())
    result = await tool.run(CashflowArgs(ts_code="600519.SH"))
    assert result["ts_code"] == "600519.SH"
    assert "n_cashflow_act" in result
    assert "n_cashflow_inv_act" in result
    assert "n_cash_flows_fnc_act" in result
    # Mock 数据 n_cashflow_act 起始 5e8 严格正 → positive_ocf True
    assert result["positive_ocf"] is True


def test_get_cashflow_args_missing_ts_code_rejected() -> None:
    with pytest.raises(ValidationError):
        CashflowArgs()  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_classify_negative_ocf() -> None:
    """n_cashflow_act = -5e8 → positive_ocf False (binary classifier 反向覆盖)."""

    class _StubTushare:
        def __init__(self, df: pd.DataFrame) -> None:
            self._df = df

        async def get_cashflow(self, *, ts_code: str, end_date: str | None = None) -> pd.DataFrame:
            return self._df

    df = pd.DataFrame(
        {
            "ts_code": ["600519.SH"],
            "end_date": ["20241231"],
            "n_cashflow_act": [-5e8],
            "n_cashflow_inv_act": [-2e8],
            "n_cash_flows_fnc_act": [1e8],
        }
    )
    tool = GetCashflowTool(tushare=cast(TushareService, _StubTushare(df)))
    result = await tool.run(CashflowArgs(ts_code="600519.SH"))
    assert result["positive_ocf"] is False
    assert result["n_cashflow_act"] == -5e8
