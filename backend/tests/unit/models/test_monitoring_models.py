"""Monitoring SQLAlchemy models — pg db_session fixture smoke."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from app.models.monitoring import (
    DetailStatus,
    MonitoringAlert,
    MonitoringRun,
    MonitoringSignal,
    Notification,
)
from sqlalchemy.orm import Session

from tests.unit._helpers import make_user


def test_monitoring_run_can_be_persisted(db_session: Session) -> None:
    user = make_user(db_session)
    run = MonitoringRun(
        id=str(uuid4()),
        user_id=user.id,
        cycle_id=str(uuid4()),
        trigger_type="cron",
        started_at=datetime.utcnow(),
        finished_at=datetime.utcnow(),
        status="success",
    )
    db_session.add(run)
    db_session.commit()
    assert db_session.query(MonitoringRun).count() == 1


def test_monitoring_signal_can_be_persisted(db_session: Session) -> None:
    user = make_user(db_session)
    run = MonitoringRun(
        id=str(uuid4()),
        user_id=user.id,
        cycle_id=str(uuid4()),
        trigger_type="cron",
        started_at=datetime.utcnow(),
        status="success",
    )
    db_session.add(run)
    db_session.flush()
    signal = MonitoringSignal(
        id=str(uuid4()),
        run_id=run.id,
        user_id=user.id,
        ts_code="600519.SH",
        rule_name="price_anomaly",
        level="yellow",
        explanation="单日 -6.2% 超 5% 阈值",
    )
    db_session.add(signal)
    db_session.commit()
    assert db_session.query(MonitoringSignal).count() == 1


def test_monitoring_alert_default_detail_status_pending(db_session: Session) -> None:
    """Spec § 3.2:新写 alert 默认 detail_status=pending。"""
    user = make_user(db_session)
    run = MonitoringRun(
        id=str(uuid4()),
        user_id=user.id,
        cycle_id=str(uuid4()),
        trigger_type="cron",
        started_at=datetime.utcnow(),
        status="success",
    )
    db_session.add(run)
    db_session.flush()
    alert = MonitoringAlert(
        id=str(uuid4()),
        run_id=run.id,
        user_id=user.id,
        ts_code="600519.SH",
        alert_level="red",
        report_json={},
    )
    db_session.add(alert)
    db_session.commit()
    saved = db_session.query(MonitoringAlert).first()
    assert saved.detail_status == DetailStatus.PENDING


def test_monitoring_alert_detail_status_state_machine(db_session: Session) -> None:
    """Spec § 3.2:pending → ready / pending → failed。"""
    user = make_user(db_session)
    run = MonitoringRun(
        id=str(uuid4()),
        user_id=user.id,
        cycle_id=str(uuid4()),
        trigger_type="cron",
        started_at=datetime.utcnow(),
        status="success",
    )
    db_session.add(run)
    db_session.flush()
    alert = MonitoringAlert(
        id=str(uuid4()),
        run_id=run.id,
        user_id=user.id,
        ts_code="600519.SH",
        alert_level="red",
        report_json={},
    )
    db_session.add(alert)
    db_session.commit()

    alert.detail_status = DetailStatus.READY
    alert.report_markdown = "# 异动详情..."
    db_session.commit()
    assert db_session.query(MonitoringAlert).first().detail_status == DetailStatus.READY


def test_notification_can_be_persisted(db_session: Session) -> None:
    user = make_user(db_session)
    run = MonitoringRun(
        id=str(uuid4()),
        user_id=user.id,
        cycle_id=str(uuid4()),
        trigger_type="cron",
        started_at=datetime.utcnow(),
        status="success",
    )
    db_session.add(run)
    db_session.flush()
    alert = MonitoringAlert(
        id=str(uuid4()),
        run_id=run.id,
        user_id=user.id,
        ts_code="600519.SH",
        alert_level="red",
        report_json={},
    )
    db_session.add(alert)
    db_session.flush()
    notif = Notification(
        id=str(uuid4()),
        alert_id=alert.id,
        channel="in_app",
        send_status="sent",
    )
    db_session.add(notif)
    db_session.commit()
    assert db_session.query(Notification).count() == 1
