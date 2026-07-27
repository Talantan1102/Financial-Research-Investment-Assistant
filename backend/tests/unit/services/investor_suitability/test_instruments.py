import pytest
from app.models.investor_suitability import Market
from app.services.investor_suitability.instruments import classify_market
from app.services.paper_trading.errors import PaperTradingError


@pytest.mark.parametrize(
    ("ts_code", "market"),
    [
        ("600000.SH", Market.MAIN),
        ("000001.SZ", Market.MAIN),
        ("300750.SZ", Market.CHINEXT),
        ("688981.SH", Market.STAR),
        ("920001.BJ", Market.BSE),
    ],
)
def test_classify_supported_a_share_boards(ts_code: str, market: Market) -> None:
    assert classify_market(ts_code) is market


@pytest.mark.parametrize("ts_code", ["920001.SH", "110001.SH", "600000.HK", "abc.SH"])
def test_classify_market_rejects_unsupported_or_ambiguous_instruments(ts_code: str) -> None:
    with pytest.raises(PaperTradingError) as caught:
        classify_market(ts_code)

    assert caught.value.code == "unsupported_instrument_market"
