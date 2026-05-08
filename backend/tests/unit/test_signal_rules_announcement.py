"""Unit tests for AnnouncementRule(LLM 分类)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest
from app.services.monitoring.signal_rules.announcement import (
    AnnouncementClassification,
    AnnouncementRule,
)
from app.services.monitoring.signal_rules.base import MonitoringSubject, SignalLevel
from app.services.monitoring.signal_rules.defaults import DEFAULT_THRESHOLDS


@pytest.fixture
def subject() -> MonitoringSubject:
    return MonitoringSubject(user_id="x", ts_code="x.SH", name="x")


def _llm(score: float) -> MagicMock:
    fake = MagicMock()
    # AnnouncementRule 用 llm.chat(...) 同步调用,返回 LLMResponse with parsed=AnnouncementClassification
    parsed = AnnouncementClassification(score=score, summary="mock")
    response = MagicMock()
    response.parsed = parsed
    response.cost_cny = 0.05
    fake.chat = MagicMock(return_value=response)
    return fake


def _ts(anns_df: pd.DataFrame) -> MagicMock:
    fake = MagicMock()
    fake.get_anns = AsyncMock(return_value=anns_df)
    return fake


@pytest.mark.asyncio
async def test_green_no_announcement(subject: MonitoringSubject) -> None:
    df = pd.DataFrame(columns=["title", "content"])
    r = await AnnouncementRule().evaluate(
        subject, _ts(df), MagicMock(), _llm(0.0), DEFAULT_THRESHOLDS["announcement"]
    )
    assert r.level == SignalLevel.GREEN


@pytest.mark.asyncio
async def test_yellow_on_mid_score(subject: MonitoringSubject) -> None:
    df = pd.DataFrame([{"title": "诉讼公告", "content": "x"}])
    r = await AnnouncementRule().evaluate(
        subject, _ts(df), MagicMock(), _llm(0.6), DEFAULT_THRESHOLDS["announcement"]
    )
    assert r.level == SignalLevel.YELLOW


@pytest.mark.asyncio
async def test_red_on_high_score(subject: MonitoringSubject) -> None:
    df = pd.DataFrame([{"title": "立案调查", "content": "x"}])
    r = await AnnouncementRule().evaluate(
        subject, _ts(df), MagicMock(), _llm(0.9), DEFAULT_THRESHOLDS["announcement"]
    )
    assert r.level == SignalLevel.RED


@pytest.mark.asyncio
async def test_green_low_score(subject: MonitoringSubject) -> None:
    df = pd.DataFrame([{"title": "常规公告", "content": "x"}])
    r = await AnnouncementRule().evaluate(
        subject, _ts(df), MagicMock(), _llm(0.2), DEFAULT_THRESHOLDS["announcement"]
    )
    assert r.level == SignalLevel.GREEN
