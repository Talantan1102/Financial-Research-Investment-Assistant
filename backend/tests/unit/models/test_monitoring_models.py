"""Monitoring SQLAlchemy models — sqlite-override smoke."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.monitoring import (
    DetailStatus,
    MonitoringAlert,
    MonitoringRun,
    MonitoringSignal,
    Notification,
)
from app.models.user import User

from tests.unit._helpers import make_user


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite:///:memory:")
    # Per-table create (matches project convention — `Base.metadata.create_all`
    # fails because unrelated models like CompanyData use JSONB w/o sqlite variant).
    User.__table__.create(engine)
    MonitoringRun.__table__.create(engine)
    MonitoringSignal.__table__.create(engine)
    MonitoringAlert.__table__.create(engine)
    Notification.__table__.create(engine)
    with Session(engine) as s:
        yield s


def test_monitoring_run_can_be_persisted(session: Session) -> None:
    user = make_user(session)
    run = MonitoringRun(
        id=str(uuid4()),
        user_id=user.id,
        cycle_id=str(uuid4()),
        trigger_type="cron",
        started_at=datetime.utcnow(),
        finished_at=datetime.utcnow(),
        status="success",
    )
    session.add(run)
    session.commit()
    assert session.query(MonitoringRun).count() == 1


def test_monitoring_signal_can_be_persisted(session: Session) -> None:
    user = make_user(session)
    run = MonitoringRun(
        id=str(uuid4()), user_id=user.id, cycle_id=str(uuid4()),
        trigger_type="cron", started_at=datetime.utcnow(), status="success",
    )
    session.add(run)
    session.flush()
    signal = MonitoringSignal(
        id=str(uuid4()),
        run_id=run.id,
        user_id=user.id,
        ts_code="600519.SH",
        rule_name="price_anomaly",
        level="yellow",
        explanation="单日 -6.2% 超 5% 阈值",
    )
    session.add(signal)
    session.commit()
    assert session.query(MonitoringSignal).count() == 1


def test_monitoring_alert_default_detail_status_pending(session: Session) -> None:
    """Spec § 3.2:新写 alert 默认 detail_status=pending。"""
    user = make_user(session)
    run = MonitoringRun(
        id=str(uuid4()), user_id=user.id, cycle_id=str(uuid4()),
        trigger_type="cron", started_at=datetime.utcnow(), status="success",
    )
    session.add(run)
    session.flush()
    alert = MonitoringAlert(
        id=str(uuid4()),
        run_id=run.id,
        user_id=user.id,
        ts_code="600519.SH",
        alert_level="red",
        report_json={},
    )
    session.add(alert)
    session.commit()
    saved = session.query(MonitoringAlert).first()
    assert saved.detail_status == DetailStatus.PENDING


def test_monitoring_alert_detail_status_state_machine(session: Session) -> None:
    """Spec § 3.2:pending → ready / pending → failed。"""
    user = make_user(session)
    run = MonitoringRun(
        id=str(uuid4()), user_id=user.id, cycle_id=str(uuid4()),
        trigger_type="cron", started_at=datetime.utcnow(), status="success",
    )
    session.add(run)
    session.flush()
    alert = MonitoringAlert(
        id=str(uuid4()), run_id=run.id, user_id=user.id, ts_code="600519.SH",
        alert_level="red", report_json={},
    )
    session.add(alert)
    session.commit()

    alert.detail_status = DetailStatus.READY
    alert.report_markdown = "# 异动详情..."
    session.commit()
    assert session.query(MonitoringAlert).first().detail_status == DetailStatus.READY


def test_notification_can_be_persisted(session: Session) -> None:
    user = make_user(session)
    run = MonitoringRun(
        id=str(uuid4()), user_id=user.id, cycle_id=str(uuid4()),
        trigger_type="cron", started_at=datetime.utcnow(), status="success",
    )
    session.add(run)
    session.flush()
    alert = MonitoringAlert(
        id=str(uuid4()), run_id=run.id, user_id=user.id, ts_code="600519.SH",
        alert_level="red", report_json={},
    )
    session.add(alert)
    session.flush()
    notif = Notification(
        id=str(uuid4()),
        alert_id=alert.id,
        channel="in_app",
        send_status="sent",
    )
    session.add(notif)
    session.commit()
    assert session.query(Notification).count() == 1
