import pytest
from app.services.portfolio_analytics import HoldingDaily, compute_daily_attribution


def _holdings():
    return [
        # 茅台:仓位3万、当日-3.5%、白酒板块-3.0%、大盘-0.8%
        HoldingDaily(ts_code="600519.SH", asset_class="stock", market_value=30000,
                     today_pct=-3.5, sector="白酒", sector_pct=-3.0, market_pct=-0.8),
        # 招行:仓位2万、当日+0.5%、银行板块+0.2%、大盘-0.8%
        HoldingDaily(ts_code="600036.SH", asset_class="stock", market_value=20000,
                     today_pct=0.5, sector="银行", sector_pct=0.2, market_pct=-0.8),
        # 基金:仓位5万、当日-0.2%(不拆板块)
        HoldingDaily(ts_code="110011.OF", asset_class="fund_otc", market_value=50000,
                     today_pct=-0.2),
    ]


def test_total_pct_is_weighted_sum() -> None:
    r = compute_daily_attribution(_holdings())
    # 0.3*-3.5 + 0.2*0.5 + 0.5*-0.2 = -1.05
    assert r.total_pct == pytest.approx(-1.05, abs=1e-9)


def test_by_class_sums_to_total() -> None:
    r = compute_daily_attribution(_holdings())
    assert r.by_class["stock"] == pytest.approx(-0.95, abs=1e-9)
    assert r.by_class["fund_otc"] == pytest.approx(-0.10, abs=1e-9)
    assert sum(r.by_class.values()) == pytest.approx(r.total_pct, abs=1e-9)


def test_stock_three_layer_closure() -> None:
    r = compute_daily_attribution(_holdings())
    s = r.stock_breakdown
    assert s["market"] == pytest.approx(-0.40, abs=1e-9)          # 0.5 * -0.8
    assert s["sector_excess"] == pytest.approx(-0.46, abs=1e-9)   # 0.3*(-2.2)+0.2*(1.0)
    assert s["idiosyncratic"] == pytest.approx(-0.09, abs=1e-9)   # 0.3*(-0.5)+0.2*(0.3)
    # 三层加总必须严丝合缝等于股票部分贡献
    assert s["market"] + s["sector_excess"] + s["idiosyncratic"] == pytest.approx(r.by_class["stock"], abs=1e-9)
