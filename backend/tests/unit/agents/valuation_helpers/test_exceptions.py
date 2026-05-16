"""L0 — InsufficientDataForModelError exception contract."""

from __future__ import annotations

import pytest


def test_insufficient_data_for_model_is_exception() -> None:
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError

    exc = InsufficientDataForModelError(
        model="dcf",
        missing_field="forecast_revenue",
        reason="tushare get_forecast 返回空",
    )
    assert isinstance(exc, Exception)
    assert exc.model == "dcf"
    assert exc.missing_field == "forecast_revenue"
    assert "tushare" in exc.reason
    assert "dcf" in str(exc)
    assert "forecast_revenue" in str(exc)


def test_insufficient_data_raises_correctly() -> None:
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError

    with pytest.raises(InsufficientDataForModelError) as exc_info:
        raise InsufficientDataForModelError(
            model="pe",
            missing_field="net_profit",
            reason="负利润,PE 失效",
        )
    assert exc_info.value.model == "pe"


def test_init_rejects_positional_args() -> None:
    """keyword-only init: 3 个 str 一字排开易混,positional 必须报错."""
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError

    with pytest.raises(TypeError):
        InsufficientDataForModelError("dcf", "forecast_revenue", "x")  # type: ignore[misc]
