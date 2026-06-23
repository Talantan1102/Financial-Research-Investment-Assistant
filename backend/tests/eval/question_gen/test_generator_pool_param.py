"""Test that pool parameterization works and is backward compatible."""

import asyncio
import pandas as pd
from eval.question_gen import generator, stock_pool

# A minimal 2-stock pool for testing
_TWO_STOCKS = (
    stock_pool.Stock("600519.SH", "贵州茅台", "白酒"),
    stock_pool.Stock("000858.SZ", "五粮液", "白酒"),
)


class _StubTushare:
    """Minimal stub: returns fixed daily data + daily_basic + fina_indicator + income."""

    async def get_daily_basic(self, *, ts_code, trade_date=None):
        return pd.DataFrame(
            [{"pe": 25.0, "pb": 8.0, "turnover_rate": 1.5, "dv_ratio": 2.0, "close": 100.0}]
        )

    async def get_fina_indicator(self, *, ts_code, end_date=None):
        rows = [
            {
                "end_date": "20241231",
                "roe": 0.25,
                "debt_to_assets": 0.35,
                "grossprofit_margin": 0.90,
                "eps": 5.0,
                "bps": 35.0,
            }
        ]
        return pd.DataFrame(rows)

    async def get_income(self, *, ts_code, end_date=None):
        rows = [{"end_date": "20241231", "revenue": 1.5e11, "n_income": 7e10}]
        return pd.DataFrame(rows)


def test_build_snapshot_cases_with_pool():
    stub = _StubTushare()
    cases = asyncio.run(
        generator.build_snapshot_cases(stub, "20260612", lambda tag: f"qg-{tag}", pool=_TWO_STOCKS)
    )
    ts_codes = {c.stocks[0] for c in cases}
    assert ts_codes == {"600519.SH", "000858.SZ"}
    # not any other stock
    assert "601398.SH" not in ts_codes


def test_by_sector_with_pool():
    result = stock_pool.by_sector(pool=_TWO_STOCKS)
    assert list(result.keys()) == ["白酒"]
    assert len(result["白酒"]) == 2


def test_by_sector_no_arg_backward_compat():
    """Calling by_sector() with no args still uses global POOL."""
    result = stock_pool.by_sector()
    assert "白酒" in result
    assert len(result["白酒"]) == 5  # original 5 白酒 stocks


def test_stock_pool_size_unchanged():
    """Original POOL still 15 stocks."""
    assert len(stock_pool.POOL) == 15
