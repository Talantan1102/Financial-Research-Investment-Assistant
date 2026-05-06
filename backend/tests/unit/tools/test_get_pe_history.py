"""Unit test for GetPeHistoryTool (v0.8.5)."""

from __future__ import annotations

import pytest
from app.services.tushare_mock_adapter import LegacyMockTushareAdapter
from app.tools.get_pe_history import (
    GetPeHistoryTool,
    PeHistoryArgs,
    _classify_valuation_band,
)
from pydantic import ValidationError


@pytest.mark.asyncio
async def test_get_pe_history_returns_band_and_percentile() -> None:
    tool = GetPeHistoryTool(tushare=LegacyMockTushareAdapter())
    result = await tool.run(PeHistoryArgs(ts_code="600519.SH"))
    assert result["ts_code"] == "600519.SH"
    assert "current_pe" in result
    assert "historical_percentile" in result
    # Mock fixture 给 percentile=0.78 → 高估带
    assert result["valuation_band"] == "高估"


def test_classify_valuation_band_boundaries() -> None:
    assert _classify_valuation_band(0.0) == "低估"
    assert _classify_valuation_band(0.29) == "低估"
    assert _classify_valuation_band(0.30) == "合理"
    assert _classify_valuation_band(0.50) == "合理"
    assert _classify_valuation_band(0.69) == "合理"
    assert _classify_valuation_band(0.70) == "高估"
    assert _classify_valuation_band(1.0) == "高估"


def test_get_pe_history_args_years_back_validation() -> None:
    with pytest.raises(ValidationError):
        PeHistoryArgs(ts_code="x", years_back=0)
    with pytest.raises(ValidationError):
        PeHistoryArgs(ts_code="x", years_back=11)
