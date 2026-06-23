"""universe.py 单测：mock tushare，不打真 tushare。"""

import asyncio

import pandas as pd
from eval.question_gen.stock_pool import Stock
from eval.question_gen.universe import load_csi800


class _MockTushare:
    """Configurable mock for universe loader tests.

    get_index_weight: accepts start_date+end_date range (new) or trade_date (legacy).
    get_stock_basic: ts_code=None → bulk all stocks; ts_code=X → single row (legacy).
    """

    def __init__(self, constituents, stock_basics, trade_date="20230101"):
        self._constituents = constituents  # list of ts_codes
        self._stock_basics = stock_basics  # dict[ts_code -> {name, industry, list_date?}]
        self._trade_date = trade_date  # trade_date to stamp on index_weight rows

    async def get_index_weight(
        self,
        *,
        index_code,
        trade_date=None,
        start_date=None,
        end_date=None,
    ):
        ref_date = trade_date or end_date or self._trade_date
        return pd.DataFrame(
            {
                "index_code": [index_code] * len(self._constituents),
                "con_code": self._constituents,
                "trade_date": [ref_date] * len(self._constituents),
            }
        )

    async def get_stock_basic(self, *, ts_code=None):
        if ts_code is None:
            # Bulk fetch: return all stocks in basics dict
            rows = list(self._stock_basics.values())
            if not rows:
                return pd.DataFrame()
            return pd.DataFrame(rows)
        if ts_code not in self._stock_basics:
            return pd.DataFrame()
        info = self._stock_basics[ts_code]
        return pd.DataFrame([info])


# as_of = 20230101 for 3y test
_AS_OF = "20230101"

_STOCKS = {
    "600519.SH": {
        "ts_code": "600519.SH",
        "name": "贵州茅台",
        "industry": "白酒",
        "list_date": "20010827",
    },
    "000858.SZ": {
        "ts_code": "000858.SZ",
        "name": "五粮液",
        "industry": "白酒",
        "list_date": "19980427",
    },
    "000001.SZ": {
        "ts_code": "000001.SZ",
        "name": "ST银行A",
        "industry": "银行",
        "list_date": "20000101",
    },  # ST → filter
    "300750.SZ": {
        "ts_code": "300750.SZ",
        "name": "宁德时代",
        "industry": "新能源",
        "list_date": "20180611",
    },  # listed 2018-06, as_of 2023-01 = 4.6y → OK
    "000999.SZ": {
        "ts_code": "000999.SZ",
        "name": "新上市股",
        "industry": "医药",
        "list_date": "20211201",
    },  # listed 2021-12, as_of 2023-01 = ~1y → filter (< 3y)
}


def test_filters_st_stocks():
    mock = _MockTushare(list(_STOCKS.keys()), _STOCKS)
    result = asyncio.run(load_csi800(mock, _AS_OF))
    names = {s.name for s in result}
    assert "ST银行A" not in names


def test_filters_new_listings():
    mock = _MockTushare(list(_STOCKS.keys()), _STOCKS)
    result = asyncio.run(load_csi800(mock, _AS_OF))
    ts_codes = {s.ts_code for s in result}
    assert "000999.SZ" not in ts_codes


def test_keeps_valid_stocks():
    mock = _MockTushare(list(_STOCKS.keys()), _STOCKS)
    result = asyncio.run(load_csi800(mock, _AS_OF))
    ts_codes = {s.ts_code for s in result}
    assert "600519.SH" in ts_codes
    assert "000858.SZ" in ts_codes
    assert "300750.SZ" in ts_codes  # listed 2018-06, as_of 2023-01 → > 3y


def test_returns_well_formed_stocks():
    mock = _MockTushare(["600519.SH"], {"600519.SH": _STOCKS["600519.SH"]})
    result = asyncio.run(load_csi800(mock, _AS_OF))
    assert len(result) == 1
    s = result[0]
    assert isinstance(s, Stock)
    assert s.ts_code == "600519.SH"
    assert s.name == "贵州茅台"
    assert s.sector == "白酒"


def test_empty_index_weight_returns_empty():
    class _EmptyMock:
        async def get_index_weight(
            self,
            *,
            index_code,
            trade_date=None,
            start_date=None,
            end_date=None,
        ):
            return pd.DataFrame()

        async def get_stock_basic(self, *, ts_code=None):
            return pd.DataFrame()

    result = asyncio.run(load_csi800(_EmptyMock(), _AS_OF))
    assert result == []


def test_takes_latest_trade_date_when_multiple_rebalance_dates():
    """index_weight 区间内有多个再平衡日时，取最新一批。"""
    # 老日期(5 月)的成分股含 ST，最新日期(6 月)的成分股干净
    may_stock = "000001.SZ"  # ST → should be filtered anyway, but not in latest batch
    june_stock = "600519.SH"

    class _MultiDateMock:
        async def get_index_weight(
            self,
            *,
            index_code,
            trade_date=None,
            start_date=None,
            end_date=None,
        ):
            return pd.DataFrame(
                {
                    "index_code": [index_code, index_code],
                    "con_code": [may_stock, june_stock],
                    "trade_date": ["20230531", "20230630"],
                }
            )

        async def get_stock_basic(self, *, ts_code=None):
            return pd.DataFrame(
                [
                    {
                        "ts_code": may_stock,
                        "name": "ST银行A",
                        "industry": "银行",
                        "list_date": "20000101",
                    },
                    {
                        "ts_code": june_stock,
                        "name": "贵州茅台",
                        "industry": "白酒",
                        "list_date": "20010827",
                    },
                ]
            )

    result = asyncio.run(load_csi800(_MultiDateMock(), "20230701"))
    ts_codes = {s.ts_code for s in result}
    # latest trade_date = 20230630 → only june_stock in batch → may_stock not in result
    assert june_stock in ts_codes
    assert may_stock not in ts_codes
