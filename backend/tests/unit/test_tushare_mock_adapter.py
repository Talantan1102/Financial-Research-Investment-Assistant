"""Unit tests for LegacyMockTushareAdapter.

Covers:
- get_balance_sheet returns a deterministic 4-row DataFrame with debt_to_assets column
  (no LLM call — critical fix from Task 4 review)
- get_cashflow / get_stk_holdernumber / get_disclosure_date / get_anns return DataFrames
  with expected column names (delegation smoke test — inner mock stubbed to avoid LLM_MODE)
- isinstance(adapter, TushareService) == True (Protocol satisfaction)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest
from app.services.tushare_mock_adapter import LegacyMockTushareAdapter
from app.services.tushare_service import TushareService

TS_CODE = "600519.SH"


# ---------------------------------------------------------------------------
# get_balance_sheet — deterministic, no _ensure_inner call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_balance_sheet_returns_four_rows() -> None:
    """get_balance_sheet is deterministic — must NOT trigger _ensure_inner (LLM)."""
    adapter = LegacyMockTushareAdapter()
    df = await adapter.get_balance_sheet(ts_code=TS_CODE)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 4, f"expected 4 rows, got {len(df)}"


@pytest.mark.asyncio
async def test_get_balance_sheet_has_debt_to_assets_column() -> None:
    """debt_to_assets column required by Task 8 FinancialRatioRule."""
    adapter = LegacyMockTushareAdapter()
    df = await adapter.get_balance_sheet(ts_code=TS_CODE)
    assert "debt_to_assets" in df.columns, f"columns={list(df.columns)}"


@pytest.mark.asyncio
async def test_get_balance_sheet_has_expected_columns() -> None:
    """All expected schema columns present."""
    adapter = LegacyMockTushareAdapter()
    df = await adapter.get_balance_sheet(ts_code=TS_CODE)
    for col in ("ts_code", "end_date", "total_assets", "total_liab", "debt_to_assets"):
        assert col in df.columns, f"missing column {col!r}; got {list(df.columns)}"


@pytest.mark.asyncio
async def test_get_balance_sheet_end_dates_are_four_quarters() -> None:
    """end_date column must contain 4 specific quarter-end dates."""
    adapter = LegacyMockTushareAdapter()
    df = await adapter.get_balance_sheet(ts_code=TS_CODE)
    expected_dates = {"20240331", "20240630", "20240930", "20241231"}
    assert set(df["end_date"]) == expected_dates, f"end_dates={set(df['end_date'])!r}"


@pytest.mark.asyncio
async def test_get_balance_sheet_debt_to_assets_values() -> None:
    """debt_to_assets values are 0.40, 0.42, 0.44, 0.46 (0.4 + i*0.02)."""
    adapter = LegacyMockTushareAdapter()
    df = await adapter.get_balance_sheet(ts_code=TS_CODE)
    sorted_df = df.sort_values("end_date").reset_index(drop=True)
    expected = [0.40, 0.42, 0.44, 0.46]
    for i, exp in enumerate(expected):
        assert abs(sorted_df["debt_to_assets"].iloc[i] - exp) < 1e-9, (
            f"row {i}: expected {exp}, got {sorted_df['debt_to_assets'].iloc[i]}"
        )


@pytest.mark.asyncio
async def test_get_balance_sheet_does_not_call_ensure_inner() -> None:
    """Deterministic path — _ensure_inner must never be called."""
    adapter = LegacyMockTushareAdapter()
    called = []

    original = adapter._ensure_inner

    def spy() -> object:
        called.append(True)
        return original()

    adapter._ensure_inner = spy  # type: ignore[method-assign]
    await adapter.get_balance_sheet(ts_code=TS_CODE)
    assert not called, "_ensure_inner was called; get_balance_sheet must be deterministic"


# ---------------------------------------------------------------------------
# Delegation smoke tests — stub _ensure_inner to avoid LLM call under LLM_MODE=none
# ---------------------------------------------------------------------------


def _make_adapter_with_stub_inner() -> tuple[LegacyMockTushareAdapter, MagicMock]:
    """Return adapter with a stubbed inner mock so delegation can be tested."""
    adapter = LegacyMockTushareAdapter()
    inner = MagicMock()
    inner.generate_cashflow = AsyncMock(
        return_value=pd.DataFrame(
            [{"ts_code": TS_CODE, "end_date": "20241231", "n_cashflow_act": 5e8}]
        )
    )
    inner.generate_stk_holdernumber = AsyncMock(
        return_value=pd.DataFrame(
            [{"ts_code": TS_CODE, "end_date": "20241231", "holder_num": 100000}]
        )
    )
    inner.generate_disclosure_date = AsyncMock(
        return_value=pd.DataFrame(columns=["ts_code", "ann_date", "end_date", "type"])
    )
    inner.generate_anns = AsyncMock(
        return_value=pd.DataFrame([{"ts_code": TS_CODE, "ann_date": "20240501", "title": "test"}])
    )
    adapter._inner = inner  # inject stub — bypasses _ensure_inner
    return adapter, inner


@pytest.mark.asyncio
async def test_get_cashflow_returns_dataframe_with_n_cashflow_act() -> None:
    adapter, _ = _make_adapter_with_stub_inner()
    df = await adapter.get_cashflow(ts_code=TS_CODE)
    assert isinstance(df, pd.DataFrame)
    assert "n_cashflow_act" in df.columns, f"columns={list(df.columns)}"


@pytest.mark.asyncio
async def test_get_stk_holdernumber_returns_dataframe_with_holder_num() -> None:
    adapter, _ = _make_adapter_with_stub_inner()
    df = await adapter.get_stk_holdernumber(ts_code=TS_CODE)
    assert isinstance(df, pd.DataFrame)
    assert "holder_num" in df.columns, f"columns={list(df.columns)}"


@pytest.mark.asyncio
async def test_get_disclosure_date_returns_dataframe() -> None:
    adapter, _ = _make_adapter_with_stub_inner()
    df = await adapter.get_disclosure_date(ts_code=TS_CODE, start="20240101", end="20241231")
    assert isinstance(df, pd.DataFrame)
    assert "ts_code" in df.columns, f"columns={list(df.columns)}"


@pytest.mark.asyncio
async def test_get_anns_returns_dataframe_with_title() -> None:
    adapter, _ = _make_adapter_with_stub_inner()
    df = await adapter.get_anns(ts_code=TS_CODE, start="20240101", end="20241231")
    assert isinstance(df, pd.DataFrame)
    assert "title" in df.columns, f"columns={list(df.columns)}"


# ---------------------------------------------------------------------------
# Protocol satisfaction
# ---------------------------------------------------------------------------


def test_adapter_is_tushare_service_instance() -> None:
    """LegacyMockTushareAdapter must satisfy TushareService Protocol at runtime."""
    adapter = LegacyMockTushareAdapter()
    assert isinstance(adapter, TushareService), (
        "LegacyMockTushareAdapter does not satisfy TushareService Protocol"
    )
