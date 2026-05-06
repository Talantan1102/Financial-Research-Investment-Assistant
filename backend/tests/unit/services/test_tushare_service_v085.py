"""v0.8.5 TushareService 加 8 个新 method 的 unit test (mock path).

Per Plan Drift: uses LegacyMockTushareAdapter (the Protocol-conforming mock),
not a hypothetical MockTushareService. Adapter must be deterministic for these
methods (no LLM dependency) so unit-layer LLM_MODE=none guard is honored.
"""

from __future__ import annotations

import pandas as pd
import pytest
from app.services.tushare_mock_adapter import LegacyMockTushareAdapter


@pytest.fixture
def mock_tushare() -> LegacyMockTushareAdapter:
    return LegacyMockTushareAdapter()


@pytest.mark.asyncio
async def test_get_balance_sheet_returns_dataframe(
    mock_tushare: LegacyMockTushareAdapter,
) -> None:
    df = await mock_tushare.get_balance_sheet(ts_code="600519.SH", end_date="20241231")
    assert isinstance(df, pd.DataFrame)
    assert "ts_code" in df.columns
    assert "total_liab" in df.columns
    assert "total_assets" in df.columns
    assert "total_cur_assets" in df.columns
    assert "total_cur_liab" in df.columns
    assert len(df) >= 1


@pytest.mark.asyncio
async def test_get_cashflow_returns_dataframe(
    mock_tushare: LegacyMockTushareAdapter,
) -> None:
    df = await mock_tushare.get_cashflow(ts_code="600519.SH", end_date="20241231")
    assert isinstance(df, pd.DataFrame)
    assert "n_cashflow_act" in df.columns  # 经营活动现金流净额
    assert "n_cashflow_inv_act" in df.columns
    assert "n_cash_flows_fnc_act" in df.columns


@pytest.mark.asyncio
async def test_get_daily_basic_returns_pe_pb_etc(
    mock_tushare: LegacyMockTushareAdapter,
) -> None:
    df = await mock_tushare.get_daily_basic(ts_code="600519.SH", trade_date="20241231")
    assert isinstance(df, pd.DataFrame)
    for col in ["pe", "pb", "ps", "dv_ratio", "total_mv", "circ_mv", "turnover_rate"]:
        assert col in df.columns


@pytest.mark.asyncio
async def test_get_pe_history_returns_percentile(
    mock_tushare: LegacyMockTushareAdapter,
) -> None:
    """get_pe_history 返回 PE 历史分位 + 当前 PE."""
    result = await mock_tushare.get_pe_history(ts_code="600519.SH", years_back=5, current_pe=64.19)
    assert isinstance(result, pd.DataFrame)
    assert "current_pe" in result.columns
    assert "historical_percentile" in result.columns
    assert 0.0 <= result["historical_percentile"].iloc[0] <= 1.0


@pytest.mark.asyncio
async def test_get_forecast_returns_业绩预告(  # noqa: N802
    mock_tushare: LegacyMockTushareAdapter,
) -> None:
    df = await mock_tushare.get_forecast(ts_code="600519.SH", period="20241231")
    assert isinstance(df, pd.DataFrame)
    # 字段: type (预告类型 预增/扭亏/略增/略减/预减/首亏/续亏/续盈/不确定)
    assert "type" in df.columns
    assert "p_change_min" in df.columns  # 预告净利润变动幅度下限
    assert "p_change_max" in df.columns


@pytest.mark.asyncio
async def test_get_dividend_history_returns_分红记录(  # noqa: N802
    mock_tushare: LegacyMockTushareAdapter,
) -> None:
    df = await mock_tushare.get_dividend_history(ts_code="600519.SH", years_back=5)
    assert isinstance(df, pd.DataFrame)
    assert "cash_div" in df.columns  # 每股现金分红
    assert "stk_div" in df.columns  # 每股送转


@pytest.mark.asyncio
async def test_get_holder_change_returns_股东户数变化(  # noqa: N802
    mock_tushare: LegacyMockTushareAdapter,
) -> None:
    df = await mock_tushare.get_holder_change(ts_code="600519.SH", years_back=2)
    assert isinstance(df, pd.DataFrame)
    assert "holder_num" in df.columns
    assert "end_date" in df.columns


@pytest.mark.asyncio
async def test_get_money_flow_returns_资金流向(  # noqa: N802
    mock_tushare: LegacyMockTushareAdapter,
) -> None:
    df = await mock_tushare.get_money_flow(
        ts_code="600519.SH", start_date="20241201", end_date="20241231"
    )
    assert isinstance(df, pd.DataFrame)
    # 大单/中单/小单买卖
    for col in ["buy_lg_amount", "sell_lg_amount", "buy_md_amount", "sell_md_amount"]:
        assert col in df.columns
