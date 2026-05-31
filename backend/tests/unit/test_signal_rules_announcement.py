"""announcement rule — 5 类公告分类(spec § 5.2 + decision 1)."""

from __future__ import annotations

import asyncio
import threading
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
    llm = _mock_llm_returns(
        AnnouncementClassification(
            type=AnnouncementType.OTHER,
            score=0.9,
            reasoning="减持不在 5 类",
        )
    )
    result = await rule.evaluate(subject, tushare, Mock(), llm, thresholds)
    assert result.level == SignalLevel.GREEN


@pytest.mark.asyncio
async def test_earnings_type_high_score_returns_red(subject, thresholds):
    """type='财报披露' + score>=0.8 → RED."""
    rule = AnnouncementRule()
    tushare = _mock_tushare_with_anns([{"title": "Q3 业绩报告", "content": "..."}])
    llm = _mock_llm_returns(
        AnnouncementClassification(
            type=AnnouncementType.EARNINGS_DISCLOSURE,
            score=0.85,
            reasoning="Q3 大幅下滑",
        )
    )
    result = await rule.evaluate(subject, tushare, Mock(), llm, thresholds)
    assert result.level == SignalLevel.RED


@pytest.mark.asyncio
async def test_warning_type_medium_score_returns_yellow(subject, thresholds):
    rule = AnnouncementRule()
    tushare = _mock_tushare_with_anns([{"title": "业绩预减", "content": "..."}])
    llm = _mock_llm_returns(
        AnnouncementClassification(
            type=AnnouncementType.PERFORMANCE_FORECAST,
            score=0.6,
            reasoning="预减 30%",
        )
    )
    result = await rule.evaluate(subject, tushare, Mock(), llm, thresholds)
    assert result.level == SignalLevel.YELLOW


@pytest.mark.asyncio
async def test_st_type_always_red(subject, thresholds):
    """ST/退市风险:即使 score 低也至少 YELLOW(spec § 5.2 这类信号灾难级)."""
    rule = AnnouncementRule()
    tushare = _mock_tushare_with_anns([{"title": "ST 提示", "content": "..."}])
    llm = _mock_llm_returns(
        AnnouncementClassification(
            type=AnnouncementType.ST_DELISTING,
            score=0.85,
            reasoning="ST 风险警示",
        )
    )
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


# ---------------------------------------------------------------------------
# C13: regression — asyncio.to_thread wraps the blocking llm.chat call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c13_llm_chat_does_not_block_event_loop(subject, thresholds):
    """C13: evaluate must not block the event loop while waiting for llm.chat.

    Strategy: make llm.chat block a threading.Event until a *concurrent*
    coroutine sets it. If asyncio.to_thread is missing, the synchronous block
    stalls the loop and the concurrent coroutine never runs → Event never set
    → the whole test hangs (or asyncio.wait_for raises TimeoutError). With
    asyncio.to_thread the block runs off the loop thread, the concurrent
    coroutine can run and set the event, and evaluate completes normally.
    """
    # Gate that the blocking llm.chat will wait on.
    gate = threading.Event()

    parsed_result = AnnouncementClassification(
        type=AnnouncementType.EARNINGS_DISCLOSURE,
        score=0.85,
        reasoning="巨亏",
    )

    def _blocking_chat(**kwargs):  # noqa: ARG001
        # Block until gate is set — represents a long-running HTTP round-trip.
        gate.wait(timeout=5.0)
        response = Mock()
        response.parsed = parsed_result
        return response

    llm = Mock()
    llm.chat = _blocking_chat

    tushare = _mock_tushare_with_anns([{"title": "Q3 巨亏公告", "content": "净利润-80%"}])

    # Concurrently release the gate after a short yield so the loop can
    # schedule both tasks. If the loop is blocked, this never runs.
    async def _release_gate():
        await asyncio.sleep(0)  # yield to let evaluate start
        gate.set()

    result, _ = await asyncio.gather(
        asyncio.wait_for(rule_evaluate_task(subject, tushare, llm, thresholds), timeout=5.0),
        _release_gate(),
    )
    assert result.level == SignalLevel.RED


async def rule_evaluate_task(subject, tushare, llm, thresholds):
    """Helper to isolate the rule.evaluate call for asyncio.gather."""
    return await AnnouncementRule().evaluate(subject, tushare, Mock(), llm, thresholds)
