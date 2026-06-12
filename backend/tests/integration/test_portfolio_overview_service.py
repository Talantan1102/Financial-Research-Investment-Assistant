import pytest
from app.services.portfolio_overview_service import build_overview
from tests.unit._helpers import make_user


@pytest.mark.asyncio
async def test_build_overview_returns_attribution_and_structure(db_session, monkeypatch):
    monkeypatch.setenv("TUSHARE_MODE", "mock")
    from app.models.position import Position

    user = make_user(db_session)

    db_session.add_all([
        Position(
            id="a",
            user_id=user.id,
            ts_code="600519.SH",
            name="茅台",
            quantity=100,
            avg_cost=1500,
            total_cost=150000,
            last_quote_price=1650,
            asset_class="stock",
        ),
        Position(
            id="f",
            user_id=user.id,
            ts_code="110011.OF",
            name="基金",
            quantity=10000,
            avg_cost=2.5,
            total_cost=25000,
            last_quote_price=2.475,
            asset_class="fund_otc",
        ),
    ])
    db_session.flush()

    ov = await build_overview(db_session, user_id=user.id)

    assert "attribution" in ov and "structure" in ov
    assert ov["structure"]["by_class"]["stock"] > 0        # 股票占比 > 0
    assert isinstance(ov["attribution"]["total_pct"], float)
    assert "total_value" in ov
    assert isinstance(ov["today_pct"], float)
    assert "by_sector" in ov["structure"]
    assert "as_of" in ov["structure"]
