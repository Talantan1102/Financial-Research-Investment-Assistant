"""Unit tests for GetFinancialsTool — regression for C55 (mislabeled ratios fix).

C55: get_financials previously stored netprofit_margin under key 'roe' and eps
     under key 'pe' — silent financial-data corruption.  Fix reads fi_row['roe']
     directly (tushare fina_indicator includes roe in both real and mock paths)
     and sets pe=0.0 (pe_ttm is not in fina_indicator; use get_daily_basic).
"""

from __future__ import annotations

from typing import cast

import pandas as pd
import pytest
from app.services.tushare_service import TushareService
from app.tools.base import ToolError
from app.tools.get_financials import FinancialsArgs, GetFinancialsTool

# ---------------------------------------------------------------------------
# Stub TushareService
# ---------------------------------------------------------------------------


class _StubTushare:
    """Minimal stub returning caller-controlled DataFrames."""

    def __init__(
        self,
        income_df: pd.DataFrame | None = None,
        fina_df: pd.DataFrame | None = None,
    ) -> None:
        self._income_df = income_df if income_df is not None else pd.DataFrame()
        self._fina_df = fina_df if fina_df is not None else pd.DataFrame()

    async def get_income(self, *, ts_code: str, end_date: str | None = None) -> pd.DataFrame:
        return self._income_df

    async def get_fina_indicator(
        self, *, ts_code: str, end_date: str | None = None
    ) -> pd.DataFrame:
        return self._fina_df

    async def aclose(self) -> None:  # pragma: no cover
        pass


def _make_income_df(
    ts_code: str = "600519.SH",
    total_revenue: float = 5e10,
    n_income_attr_p: float = 1.5e10,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_code": [ts_code],
            "end_date": ["20241231"],
            "total_revenue": [total_revenue],
            "n_income_attr_p": [n_income_attr_p],
        }
    )


def _make_fina_df(
    ts_code: str = "600519.SH",
    roe: float = 0.28,
    netprofit_margin: float = 0.45,
    eps: float = 8.70,
) -> pd.DataFrame:
    """DataFrame with distinct roe, netprofit_margin, and eps so misread is detectable."""
    return pd.DataFrame(
        {
            "ts_code": [ts_code],
            "end_date": ["20241231"],
            "roe": [roe],
            "netprofit_margin": [netprofit_margin],
            "eps": [eps],
        }
    )


# ---------------------------------------------------------------------------
# C55 regression: roe key must equal roe column (not netprofit_margin)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_roe_reads_from_roe_column_not_netprofit_margin() -> None:
    """C55: output['roe'] must equal the roe field, not netprofit_margin."""
    fina_df = _make_fina_df(roe=0.28, netprofit_margin=0.45, eps=8.70)
    stub = _StubTushare(income_df=_make_income_df(), fina_df=fina_df)
    tool = GetFinancialsTool(tushare=cast(TushareService, stub))

    result = await tool.run(FinancialsArgs(ts_code="600519.SH"))

    # Must match roe (0.28), not netprofit_margin (0.45)
    assert result["roe"] == pytest.approx(0.28), (
        f"roe={result['roe']!r} should be 0.28 (roe), not 0.45 (netprofit_margin)"
    )


@pytest.mark.asyncio
async def test_pe_is_zero_not_eps() -> None:
    """C55: pe_ttm is not in fina_indicator; pe must be 0.0, not eps (8.70)."""
    fina_df = _make_fina_df(roe=0.28, netprofit_margin=0.45, eps=8.70)
    stub = _StubTushare(income_df=_make_income_df(), fina_df=fina_df)
    tool = GetFinancialsTool(tushare=cast(TushareService, stub))

    result = await tool.run(FinancialsArgs(ts_code="600519.SH"))

    # Must be 0.0, NOT eps value (8.70)
    assert result["pe"] == pytest.approx(0.0), (
        f"pe={result['pe']!r} should be 0.0 (sourced from daily_basic), not eps={8.70}"
    )


@pytest.mark.asyncio
async def test_roe_and_netprofit_margin_are_distinguishable() -> None:
    """Cross-check: roe and netprofit_margin must not be the same value in result."""
    # Use clearly distinct values to detect the mislabeling
    fina_df = _make_fina_df(roe=0.28, netprofit_margin=0.45, eps=8.70)
    stub = _StubTushare(income_df=_make_income_df(), fina_df=fina_df)
    tool = GetFinancialsTool(tushare=cast(TushareService, stub))

    result = await tool.run(FinancialsArgs(ts_code="600519.SH"))

    # Before the fix result['roe'] would be 0.45 (netprofit_margin); after fix it is 0.28 (roe).
    assert result["roe"] != pytest.approx(0.45), (
        "result['roe'] must not equal netprofit_margin (0.45) — that was the old bug"
    )


# ---------------------------------------------------------------------------
# Baseline functionality: income fields still extracted correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revenue_and_net_profit_extracted() -> None:
    stub = _StubTushare(
        income_df=_make_income_df(total_revenue=5e10, n_income_attr_p=1.5e10),
        fina_df=_make_fina_df(),
    )
    tool = GetFinancialsTool(tushare=cast(TushareService, stub))
    result = await tool.run(FinancialsArgs(ts_code="600519.SH"))

    assert result["revenue"] == pytest.approx(5e10)
    assert result["net_profit"] == pytest.approx(1.5e10)
    assert result["ts_code"] == "600519.SH"
    assert result["period"] == "latest"


@pytest.mark.asyncio
async def test_empty_fina_df_returns_zero_roe() -> None:
    """Empty fina_indicator → roe=0.0 (graceful fallback)."""
    stub = _StubTushare(income_df=_make_income_df(), fina_df=pd.DataFrame())
    tool = GetFinancialsTool(tushare=cast(TushareService, stub))
    result = await tool.run(FinancialsArgs(ts_code="600519.SH"))

    assert result["roe"] == pytest.approx(0.0)
    assert result["pe"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_tushare_exception_raises_tool_error() -> None:
    class _FailingTushare:
        async def get_income(self, *, ts_code: str, end_date: str | None = None) -> pd.DataFrame:
            raise ConnectionError("network failure")

        async def get_fina_indicator(
            self, *, ts_code: str, end_date: str | None = None
        ) -> pd.DataFrame:
            raise ConnectionError("network failure")

        async def aclose(self) -> None:  # pragma: no cover
            pass

    tool = GetFinancialsTool(tushare=cast(TushareService, _FailingTushare()))
    with pytest.raises(ToolError, match="TushareService call failed"):
        await tool.run(FinancialsArgs(ts_code="600519.SH"))
