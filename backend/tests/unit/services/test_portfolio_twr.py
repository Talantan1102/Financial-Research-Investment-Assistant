import pytest
from app.services.portfolio_analytics import DailySnap, compute_twr


def test_twr_excludes_position_changes() -> None:
    # 第1天→第2天:持仓不变,价从100→110,日收益+10%
    # 第2天→第3天:期初(第2天)持仓在第3天估值得日收益;即便第3天加了仓也不算进收益
    snaps = [
        DailySnap(date="20261112", holdings={"A": (100, 100.0)}),  # (qty, price)
        DailySnap(date="20261113", holdings={"A": (100, 110.0)}),
        DailySnap(date="20261114", holdings={"A": (200, 99.0)}),  # 加了100股 + 价跌到99
    ]
    twr = compute_twr(snaps)
    # day1 收益 = 110/100-1 = +0.10
    # day2 收益:用第2天持仓(100股)在 day3 价 99 vs day2 价 110 = 99/110-1 = -0.10
    #   注意:第3天多出的100股是"加仓",不计入收益
    # 链式:(1.10)*(0.90)-1 = -0.01
    assert twr["cumulative"] == pytest.approx(-0.01, abs=1e-9)
    assert twr["daily"][0] == pytest.approx(0.10, abs=1e-9)
    assert twr["daily"][1] == pytest.approx(-0.10, abs=1e-9)
