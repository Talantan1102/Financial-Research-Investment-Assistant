"""announcement rule — 5 类公告分类(spec § 5.2 + decision 1)."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pandas as pd
import pytest

from app.services.monitoring.scope import MonitoringSubject
from app.services.monitoring.signal_rules.announcement import (
    AnnouncementClassification,
    AnnouncementRule,
    AnnouncementType,
)
from app.services.monitoring.signal_rules.base import SignalLevel


@pytest.fixture
def subject() -> MonitoringSubject:
    return MonitoringSubject(user_id="u1", ts_code="600519.SH", name="贵州茅台")


@pytest.fixture
def thresholds() -> dict[str, float]:
    return {"red_threshold": 0.8, "yellow_lower": 0.5}


def _mock_tushare_with_anns(rows: list[dict[str, str]]) -> Mock:
    df = pd.DataFrame(rows)
    tushare = Mock()
    tushare.get_anns = AsyncMock(return_value=df)
    return tushare


def _mock_llm_returns(parsed: AnnouncementClassification) -> Mock:
    llm = Mock()
    response = Mock()
    response.parsed = parsed
    llm.chat = Mock(return_value=response)
    return llm


@pytest.mark.asyncio
async def test_other_type_returns_green(subject, thresholds):
    """type='其他' → GREEN(spec § 5.2 不做的:减持/回购等)."""
    rule = AnnouncementRule()
    tushare = _mock_tushare_with_anns([{"title": "高管减持", "content": "减持 1%"}])
    llm = _mock_llm_returns(AnnouncementClassification(
        type=AnnouncementType.OTHER, score=0.9, reasoning="减持不在 5 类",
    ))
    result = await rule.evaluate(subject, tushare, Mock(), llm, thresholds)
    assert result.level == SignalLevel.GREEN


@pytest.mark.asyncio
async def test_earnings_type_high_score_returns_red(subject, thresholds):
    """type='财报披露' + score>=0.8 → RED."""
    rule = AnnouncementRule()
    tushare = _mock_tushare_with_anns([{"title": "Q3 业绩报告", "content": "..."}])
    llm = _mock_llm_returns(AnnouncementClassification(
        type=AnnouncementType.EARNINGS_DISCLOSURE, score=0.85, reasoning="Q3 大幅下滑",
    ))
    result = await rule.evaluate(subject, tushare, Mock(), llm, thresholds)
    assert result.level == SignalLevel.RED


@pytest.mark.asyncio
async def test_warning_type_medium_score_returns_yellow(subject, thresholds):
    rule = AnnouncementRule()
    tushare = _mock_tushare_with_anns([{"title": "业绩预减", "content": "..."}])
    llm = _mock_llm_returns(AnnouncementClassification(
        type=AnnouncementType.PERFORMANCE_FORECAST, score=0.6, reasoning="预减 30%",
    ))
    result = await rule.evaluate(subject, tushare, Mock(), llm, thresholds)
    assert result.level == SignalLevel.YELLOW


@pytest.mark.asyncio
async def test_st_type_always_red(subject, thresholds):
    """ST/退市风险:即使 score 低也至少 YELLOW(spec § 5.2 这类信号灾难级)."""
    rule = AnnouncementRule()
    tushare = _mock_tushare_with_anns([{"title": "ST 提示", "content": "..."}])
    llm = _mock_llm_returns(AnnouncementClassification(
        type=AnnouncementType.ST_DELISTING, score=0.85, reasoning="ST 风险警示",
    ))
    result = await rule.evaluate(subject, tushare, Mock(), llm, thresholds)
    assert result.level == SignalLevel.RED


@pytest.mark.asyncio
async def test_no_anns_returns_green(subject, thresholds):
    rule = AnnouncementRule()
    tushare = _mock_tushare_with_anns([])
    result = await rule.evaluate(subject, tushare, Mock(), Mock(), thresholds)
    assert result.level == SignalLevel.GREEN


@pytest.mark.asyncio
async def test_llm_parse_failure_returns_green(subject, thresholds):
    rule = AnnouncementRule()
    tushare = _mock_tushare_with_anns([{"title": "x", "content": "y"}])
    llm = Mock()
    response = Mock()
    response.parsed = None  # parse failed
    llm.chat = Mock(return_value=response)
    result = await rule.evaluate(subject, tushare, Mock(), llm, thresholds)
    assert result.level == SignalLevel.GREEN
    assert "解析失败" in result.explanation
