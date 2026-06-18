"""operators 确定性单测：纯函数，手写数据，不依赖网络/DB/LLM。"""

import pytest

from eval.question_gen import operators
from eval.question_gen.operators import (
    correlation_pair,
    filter_by,
    rank_by,
    single,
)


def _stock(close=None, dates=None, pct_chg=None):
    close = close or []
    if pct_chg is None and len(close) >= 2:
        # 涨幅/回撤/CAGR 现走复权路径(pct_chg 累乘);非拆股数据从 close 反推 pct_chg,
        # 累乘回去是同一条路径 → 预期值不变。首根置 0(adjusted_path 跳过)。
        pct_chg = [0.0] + [(close[i] / close[i - 1] - 1.0) * 100.0 for i in range(1, len(close))]
    return {
        "close": close,
        "dates": dates or [],
        "pct_chg": pct_chg or [],
    }


# ---- single 派发 ----


def test_single_return():
    # 99/100 - 1 = -0.01
    assert single("涨幅", _stock(close=[100.0, 110.0, 99.0])) == pytest.approx(-0.01)


def test_single_drawdown():
    # 峰值 110 -> 1 - 99/110 = 0.1
    assert single("回撤", _stock(close=[100.0, 110.0, 99.0])) == pytest.approx(0.1)


def test_single_volatility_positive():
    vol = single("波动", _stock(pct_chg=[1.0, -2.0, 3.0, -1.5, 2.0]))
    assert vol > 0


def test_single_cagr():
    # (121/100)^(1/2) - 1 = 1.1 - 1 = 0.10
    assert single("CAGR", _stock(close=[100.0, 121.0]), years=2.0) == pytest.approx(0.10)


def test_single_unknown_raises():
    with pytest.raises(ValueError):
        single("夏普", _stock(close=[100.0, 110.0]))


# ---- rank_by ----


def test_rank_by_return_top2_descending():
    per_stock = {
        "A": _stock(close=[100.0, 130.0]),  # +0.30
        "B": _stock(close=[100.0, 90.0]),  # -0.10
        "C": _stock(close=[100.0, 110.0]),  # +0.10
    }
    ranked = rank_by("涨幅", per_stock, top_k=2)
    assert [t for t, _ in ranked] == ["A", "C"]
    assert ranked[0][1] == pytest.approx(0.30)
    assert ranked[1][1] == pytest.approx(0.10)


def test_rank_by_ascending():
    per_stock = {
        "A": _stock(close=[100.0, 130.0]),  # +0.30
        "B": _stock(close=[100.0, 90.0]),  # -0.10
        "C": _stock(close=[100.0, 110.0]),  # +0.10
    }
    ranked = rank_by("涨幅", per_stock, top_k=1, descending=False)
    assert [t for t, _ in ranked] == ["B"]
    assert ranked[0][1] == pytest.approx(-0.10)


# ---- filter_by ----


def test_filter_by_two_predicates():
    per_stock = {
        # 涨幅 +0.10 (>0) 且 回撤 0.0 (<0.2) -> 满足
        "GOOD": _stock(close=[100.0, 110.0]),
        # 涨幅 -0.10 (不 >0) -> 不满足
        "BAD": _stock(close=[100.0, 90.0]),
    }
    keep = filter_by(per_stock, [("涨幅", ">", 0.0), ("回撤", "<", 0.2)])
    assert keep == {"GOOD"}


def test_filter_by_none_match_returns_empty():
    per_stock = {
        "X": _stock(close=[100.0, 90.0]),  # 涨幅 < 0
        "Y": _stock(close=[100.0, 80.0]),  # 涨幅 < 0
    }
    keep = filter_by(per_stock, [("涨幅", ">", 0.0)])
    assert keep == set()


# ---- correlation_pair ----


def test_correlation_pair_perfect_positive():
    dates = ["20240101", "20240102", "20240103", "20240104"]
    a = _stock(dates=dates, pct_chg=[1.0, 2.0, -1.0, 3.0])
    b = _stock(dates=dates, pct_chg=[2.0, 4.0, -2.0, 6.0])  # b = 2a
    assert correlation_pair(a, b) == pytest.approx(1.0)


def test_snapshot_lookup_maps_each_indicator():
    snap = {"pe": 25.3, "pb": 8.1, "turnover_rate": 1.5, "dv_ratio": 2.0}
    assert operators.snapshot_lookup("PE", snap) == 25.3
    assert operators.snapshot_lookup("PB", snap) == 8.1
    assert operators.snapshot_lookup("换手率", snap) == 1.5
    assert operators.snapshot_lookup("股息率", snap) == 2.0


def test_snapshot_lookup_unknown_raises():
    import pytest

    with pytest.raises(ValueError):
        operators.snapshot_lookup("未知指标", {"pe": 1.0})


def test_snapshot_lookup_none_for_missing_value():
    # 亏损股 PE 为 None → 返回 None(不抛)
    assert (
        operators.snapshot_lookup("PE", {"pe": None, "pb": 5.0, "turnover_rate": 1.0, "dv_ratio": 0.0})
        is None
    )
    nan = float("nan")
    assert (
        operators.snapshot_lookup("PB", {"pe": 1.0, "pb": nan, "turnover_rate": 1.0, "dv_ratio": 0.0})
        is None
    )
