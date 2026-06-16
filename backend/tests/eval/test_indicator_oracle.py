"""indicator_oracle 冻结口径参考实现单测。"""

from __future__ import annotations

import math

import pytest
from eval.indicator_oracle import (
    annual_volatility,
    cagr,
    correlation,
    interval_return,
    max_drawdown,
    pe_percentile,
)


def test_interval_return() -> None:
    assert interval_return([100.0, 90.0]) == pytest.approx(-0.10)
    assert interval_return([100.0, 130.0]) == pytest.approx(0.30)


def test_interval_return_guards() -> None:
    with pytest.raises(ValueError):
        interval_return([100.0])
    with pytest.raises(ValueError):
        interval_return([0.0, 100.0])


def test_max_drawdown() -> None:
    # 峰 120 → 谷 90:回撤 = 1 − 90/120 = 0.25
    assert max_drawdown([100.0, 120.0, 90.0, 110.0]) == pytest.approx(0.25)
    # 单调上涨无回撤
    assert max_drawdown([100.0, 110.0, 120.0]) == pytest.approx(0.0)


def test_annual_volatility_ddof1_sqrt252() -> None:
    # pct=[1,-1](%) → rets=[0.01,-0.01];std(ddof=1)=√(0.0002)=0.014142;×√252
    expected = math.sqrt(0.0002) * math.sqrt(252)
    assert annual_volatility([1.0, -1.0]) == pytest.approx(expected, rel=1e-6)


def test_correlation_perfect_and_uses_pct() -> None:
    # 完全正相关:pct_b = 2×pct_a → r=1
    r = correlation(["d1", "d2", "d3"], [1.0, 2.0, 3.0], ["d1", "d2", "d3"], [2.0, 4.0, 6.0])
    assert r == pytest.approx(1.0)


def test_correlation_aligns_by_date() -> None:
    # 只用共同交易日 d2/d3:pct_a=[2,3] vs pct_b=[2,3] → r=1(d1/d4 被剔)
    r = correlation(["d1", "d2", "d3"], [1.0, 2.0, 3.0], ["d2", "d3", "d4"], [2.0, 3.0, 9.0])
    assert r == pytest.approx(1.0)


def test_cagr() -> None:
    # 121/100 = 1.21,开 2 次方根 = 1.1 → 0.10
    assert cagr([100.0, 121.0], 2.0) == pytest.approx(0.10)


def test_pe_percentile() -> None:
    # 历史 [10,20,30,40] 中 < 25 的有 2 个 → 0.5
    assert pe_percentile([10.0, 20.0, 30.0, 40.0], 25.0) == pytest.approx(0.5)
    # 当前最低 → 0%
    assert pe_percentile([10.0, 20.0, 30.0], 5.0) == pytest.approx(0.0)
