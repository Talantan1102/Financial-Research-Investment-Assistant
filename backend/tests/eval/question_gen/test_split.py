"""split.py 单测：不相交/均衡/确定性。"""

import pytest
from eval.question_gen.split import split_by_stock
from eval.question_gen.stock_pool import Stock, POOL


def _make_stocks(n_per_sector: dict[str, int]) -> list[Stock]:
    stocks = []
    for sector, n in n_per_sector.items():
        for i in range(n):
            stocks.append(
                Stock(ts_code=f"{sector}-{i:03d}.SH", name=f"{sector}股{i}", sector=sector)
            )
    return stocks


def test_disjoint_by_ts_code():
    """Three splits must be pairwise disjoint on ts_code."""
    stocks = _make_stocks({"白酒": 10, "银行": 8, "新能源": 6, "医药": 4})
    train, val, test = split_by_stock(stocks)
    train_codes = {s.ts_code for s in train}
    val_codes = {s.ts_code for s in val}
    test_codes = {s.ts_code for s in test}
    assert train_codes & val_codes == set(), "train ∩ val must be empty"
    assert train_codes & test_codes == set(), "train ∩ test must be empty"
    assert val_codes & test_codes == set(), "val ∩ test must be empty"


def test_all_stocks_covered():
    """Union of three splits = original stock set."""
    stocks = _make_stocks({"白酒": 10, "银行": 8, "新能源": 6})
    train, val, test = split_by_stock(stocks)
    all_codes = {s.ts_code for s in stocks}
    split_codes = {s.ts_code for s in train} | {s.ts_code for s in val} | {s.ts_code for s in test}
    assert split_codes == all_codes


def test_each_sector_represented_in_train():
    """With enough stocks per sector, train gets at least 1 per sector."""
    stocks = _make_stocks({"白酒": 5, "银行": 5, "新能源": 5})
    train, val, test = split_by_stock(stocks)
    train_sectors = {s.sector for s in train}
    assert "白酒" in train_sectors
    assert "银行" in train_sectors
    assert "新能源" in train_sectors


def test_deterministic_same_seed():
    stocks = _make_stocks({"白酒": 10, "银行": 8, "新能源": 6})
    train1, val1, test1 = split_by_stock(stocks, seed=42)
    train2, val2, test2 = split_by_stock(stocks, seed=42)
    assert [s.ts_code for s in train1] == [s.ts_code for s in train2]
    assert [s.ts_code for s in val1] == [s.ts_code for s in val2]
    assert [s.ts_code for s in test1] == [s.ts_code for s in test2]


def test_different_seeds_give_different_splits():
    stocks = _make_stocks({"白酒": 10, "银行": 8, "新能源": 6})
    train1, _, _ = split_by_stock(stocks, seed=42)
    train2, _, _ = split_by_stock(stocks, seed=99)
    # With enough stocks, different seeds should produce different orderings
    assert [s.ts_code for s in train1] != [s.ts_code for s in train2]


def test_ratios_roughly_maintained():
    """Train should be ~80% of total."""
    stocks = _make_stocks({"白酒": 10, "银行": 10, "新能源": 10, "医药": 10})
    train, val, test = split_by_stock(stocks, ratios=(0.8, 0.1, 0.1))
    total = len(train) + len(val) + len(test)
    assert total == 40
    assert len(train) >= 28  # at least 70%
    assert len(train) <= 36  # at most 90%


def test_with_pool_stocks():
    """Test with the actual POOL (15 stocks) for integration."""
    stocks = list(POOL)
    train, val, test = split_by_stock(stocks)
    train_codes = {s.ts_code for s in train}
    test_codes = {s.ts_code for s in test}
    assert train_codes & test_codes == set(), "POOL: train ∩ test must be empty"
