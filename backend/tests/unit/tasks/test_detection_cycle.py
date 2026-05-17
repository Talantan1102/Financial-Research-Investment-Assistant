"""detection_cycle Celery task — eager mode + mock SignalDetector."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from app.models.monitoring import (
    DetailStatus,
    MonitoringAlert,
    MonitoringRun,
)
from app.models.position import Position
from app.models.user import User
from app.services.monitoring.signal_rules.base import SignalLevel, SignalResult
from sqlalchemy.orm import Session


@pytest.fixture(autouse=True)
def celery_eager(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    monkeypatch.setenv("CELERY_TASK_EAGER_PROPAGATES", "1")


def _make_user(session: Session) -> User:
    uid = uuid4().hex[:8]
    u = User(
        id=str(uuid4()),
        username=f"user-{uid}",
        email=f"u-{uid}@t",
        hashed_password="x",
        is_active=True,
    )
    session.add(u)
    session.flush()
    return u


def _make_position(session: Session, user: User, ts_code: str) -> Position:
    p = Position(
        id=str(uuid4()),
        user_id=user.id,
        ts_code=ts_code,
        name=f"name-{ts_code}",
        quantity=100,
        avg_cost=Decimal("100"),
        total_cost=Decimal("10000"),
        realized_pnl=Decimal("0"),
    )
    session.add(p)
    session.flush()
    return p


def test_detection_cycle_creates_run_per_user(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """每个有持仓的 user 在该 cycle 内一行 monitoring_run."""
    user = _make_user(db_session)
    _make_position(db_session, user, "600519.SH")
    db_session.commit()

    # Mock SignalDetector 全 GREEN
    mock_detector = MagicMock()
    mock_detector.detect = AsyncMock(
        return_value=(
            SignalLevel.GREEN,
            [SignalResult(rule_name="x", level=SignalLevel.GREEN, explanation="ok")],
        )
    )

    with (
        patch("app.tasks.monitoring._build_detector", return_value=mock_detector),
        patch("app.tasks.monitoring._get_session", return_value=db_session),
    ):
        from app.tasks.monitoring import detection_cycle

        detection_cycle.apply().get()

    runs = db_session.query(MonitoringRun).filter_by(user_id=user.id).all()
    assert len(runs) >= 1


def test_detection_cycle_yellow_creates_alert_with_pending_status(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _make_user(db_session)
    _make_position(db_session, user, "600519.SH")
    db_session.commit()

    mock_detector = MagicMock()
    mock_detector.detect = AsyncMock(
        return_value=(
            SignalLevel.YELLOW,
            [SignalResult(rule_name="price_anomaly", level=SignalLevel.YELLOW, explanation="-6%")],
        )
    )

    enqueued = []

    def _fake_delay(alert_id: str, **kwargs) -> None:
        enqueued.append(alert_id)

    with (
        patch("app.tasks.monitoring._build_detector", return_value=mock_detector),
        patch("app.tasks.monitoring._get_session", return_value=db_session),
        patch("app.tasks.monitoring.generate_detail_card.delay", side_effect=_fake_delay),
    ):
        from app.tasks.monitoring import detection_cycle

        detection_cycle.apply().get()

    alerts = db_session.query(MonitoringAlert).filter_by(user_id=user.id).all()
    assert len(alerts) == 1
    assert alerts[0].alert_level == "yellow"
    assert alerts[0].detail_status == DetailStatus.PENDING
    assert len(enqueued) == 1  # generate_detail_card enqueued for the alert


def test_detection_cycle_dedupes_ts_code_across_users(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同 ts_code 跨 user 共享 SignalDetector 一次调用(spec § 4.5 去重节省 cost)."""
    u1 = _make_user(db_session)
    u2 = _make_user(db_session)
    _make_position(db_session, u1, "600519.SH")
    _make_position(db_session, u2, "600519.SH")
    db_session.commit()

    detect_calls = []
    mock_detector = MagicMock()

    async def _detect_spy(subject, *args, **kwargs):
        detect_calls.append(subject.ts_code)
        return (SignalLevel.GREEN, [])

    mock_detector.detect = _detect_spy

    with (
        patch("app.tasks.monitoring._build_detector", return_value=mock_detector),
        patch("app.tasks.monitoring._get_session", return_value=db_session),
    ):
        from app.tasks.monitoring import detection_cycle

        detection_cycle.apply().get()

    assert detect_calls.count("600519.SH") == 1  # 去重


def test_detection_cycle_updates_position_last_quote(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """spec § 4.5 顺手刷新 Position.last_quote_price/at."""
    user = _make_user(db_session)
    pos = _make_position(db_session, user, "600519.SH")
    pos_id = pos.id  # capture before impl session.close() detaches the instance
    db_session.commit()

    mock_detector = MagicMock()
    mock_detector.detect = AsyncMock(
        return_value=(
            SignalLevel.GREEN,
            [
                SignalResult(
                    rule_name="price_anomaly",
                    level=SignalLevel.GREEN,
                    explanation="ok",
                    raw_data_ref={"close": 1500.0},  # quote snapshot
                )
            ],
        )
    )

    with (
        patch("app.tasks.monitoring._build_detector", return_value=mock_detector),
        patch("app.tasks.monitoring._get_session", return_value=db_session),
    ):
        from app.tasks.monitoring import detection_cycle

        detection_cycle.apply().get()

    refreshed = db_session.query(Position).filter_by(id=pos_id).one()
    assert refreshed.last_quote_price == Decimal("1500.0")
    assert refreshed.last_quote_at is not None
