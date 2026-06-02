"""Unit tests for SignalDetector."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from app.services.monitoring.signal_detector import SignalDetector
from app.services.monitoring.signal_rules.base import (
    MonitoringSubject,
    SignalLevel,
    SignalResult,
    SignalRule,
)

if TYPE_CHECKING:
    from app.services.bocha_factory import BochaService
    from app.services.llm_service import LLMService
    from app.services.tushare_service import TushareService


def _make_fake_rule(rule_name: str, level: SignalLevel) -> SignalRule:
    """Factory: build a concrete SignalRule subclass with a fixed name and level."""

    class _FakeRule(SignalRule):
        name = rule_name

        async def evaluate(
            self,
            subject: MonitoringSubject,
            tushare: TushareService,
            bocha: BochaService,
            llm: LLMService,
            thresholds: dict[str, float],
        ) -> SignalResult:
            return SignalResult(rule_name=self.name, level=level, explanation="fake")

    return _FakeRule()


@pytest.fixture
def subject() -> MonitoringSubject:
    return MonitoringSubject(user_id="x", ts_code="x.SH", name="x")


@pytest.mark.asyncio
async def test_all_green_returns_green(subject: MonitoringSubject) -> None:
    detector = SignalDetector(
        rules=[_make_fake_rule("a", SignalLevel.GREEN), _make_fake_rule("b", SignalLevel.GREEN)]
    )
    overall, results = await detector.detect(subject, MagicMock(), MagicMock(), MagicMock(), {})
    assert overall == SignalLevel.GREEN
    assert len(results) == 2


@pytest.mark.asyncio
async def test_one_yellow_returns_yellow(subject: MonitoringSubject) -> None:
    detector = SignalDetector(
        rules=[_make_fake_rule("a", SignalLevel.GREEN), _make_fake_rule("b", SignalLevel.YELLOW)]
    )
    overall, _ = await detector.detect(subject, MagicMock(), MagicMock(), MagicMock(), {})
    assert overall == SignalLevel.YELLOW


@pytest.mark.asyncio
async def test_one_red_returns_red(subject: MonitoringSubject) -> None:
    detector = SignalDetector(
        rules=[_make_fake_rule("a", SignalLevel.YELLOW), _make_fake_rule("b", SignalLevel.RED)]
    )
    overall, _ = await detector.detect(subject, MagicMock(), MagicMock(), MagicMock(), {})
    assert overall == SignalLevel.RED


@pytest.mark.asyncio
async def test_rule_exception_surfaced_as_red(subject: MonitoringSubject) -> None:
    """规则抛错不阻塞其他 rule,但必须 fail-loud:该 rule 算 RED(不是 GREEN),
    overall 也 RED,使 alert gate 触发可见告警(hard rule 4 No-Silent-Fallback)。
    旧行为(降级 GREEN)会把数据/LLM 故障伪装成干净扫描,静默吞掉真告警。"""

    class BoomRule(SignalRule):
        name = "boom"

        async def evaluate(
            self,
            subject: MonitoringSubject,
            tushare: TushareService,
            bocha: BochaService,
            llm: LLMService,
            thresholds: dict[str, float],
        ) -> SignalResult:
            raise RuntimeError("kaboom")

    detector = SignalDetector(rules=[BoomRule(), _make_fake_rule("ok", SignalLevel.GREEN)])
    overall, results = await detector.detect(subject, MagicMock(), MagicMock(), MagicMock(), {})
    assert overall == SignalLevel.RED
    assert len(results) == 2
    boom = next(r for r in results if r.rule_name == "boom")
    assert boom.level == SignalLevel.RED
    assert "error" in boom.explanation.lower()
