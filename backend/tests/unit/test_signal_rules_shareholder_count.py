"""Unit tests for ShareholderCountRule."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest
from app.services.monitoring.signal_rules.base import MonitoringSubject, SignalLevel
from app.services.monitoring.signal_rules.defaults import DEFAULT_THRESHOLDS
from app.services.monitoring.signal_rules.shareholder_count import ShareholderCountRule


@pytest.fixture
def subject() -> MonitoringSubject:
    return MonitoringSubject(user_id="x", ts_code="x.SH", name="x")


def _ts(df: pd.DataFrame) -> MagicMock:
    fake = MagicMock()
    fake.get_stk_holdernumber = AsyncMock(return_value=df)
    return fake


@pytest.mark.asyncio
async def test_green_stable(subject: MonitoringSubject) -> None:
    df = pd.DataFrame(
        [
            {"end_date": ed, "holder_num": v}
            for ed, v in [
                ("20240930", 100000),
                ("20241231", 99000),
            ]
        ]
    )
    r = await ShareholderCountRule().evaluate(
        subject, _ts(df), MagicMock(), MagicMock(), DEFAULT_THRESHOLDS["shareholder_count"]
    )
    assert r.level == SignalLevel.GREEN


@pytest.mark.asyncio
async def test_yellow_15pct_drop(subject: MonitoringSubject) -> None:
    df = pd.DataFrame(
        [
            {"end_date": ed, "holder_num": v}
            for ed, v in [
                ("20240930", 100000),
                ("20241231", 85000),
            ]
        ]
    )
    r = await ShareholderCountRule().evaluate(
        subject, _ts(df), MagicMock(), MagicMock(), DEFAULT_THRESHOLDS["shareholder_count"]
    )
    assert r.level == SignalLevel.YELLOW


@pytest.mark.asyncio
async def test_red_25pct_drop(subject: MonitoringSubject) -> None:
    df = pd.DataFrame(
        [
            {"end_date": ed, "holder_num": v}
            for ed, v in [
                ("20240930", 100000),
                ("20241231", 75000),
            ]
        ]
    )
    r = await ShareholderCountRule().evaluate(
        subject, _ts(df), MagicMock(), MagicMock(), DEFAULT_THRESHOLDS["shareholder_count"]
    )
    assert r.level == SignalLevel.RED


@pytest.mark.asyncio
async def test_green_when_data_insufficient(subject: MonitoringSubject) -> None:
    df = pd.DataFrame(columns=["end_date", "holder_num"])
    r = await ShareholderCountRule().evaluate(
        subject, _ts(df), MagicMock(), MagicMock(), DEFAULT_THRESHOLDS["shareholder_count"]
    )
    assert r.level == SignalLevel.GREEN
