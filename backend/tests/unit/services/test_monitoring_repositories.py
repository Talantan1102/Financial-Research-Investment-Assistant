"""Monitoring repos — db_session fixture + cycle_id UNIQUE."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from app.models.user import User
from app.services.monitoring.repositories import (
    MonitoringAlertRepo,
    MonitoringRunRepo,
    MonitoringSignalRepo,
    NotificationRepo,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.unit._helpers import make_user


@pytest.fixture
def user(db_session: Session) -> User:
    return make_user(db_session)


def test_run_repo_create_and_get(db_session: Session, user: User) -> None:
    repo = MonitoringRunRepo(db_session)
    run = repo.create(
        user_id=user.id,
        cycle_id=str(uuid4()),
        trigger_type="cron",
        started_at=datetime.utcnow(),
    )
    fetched = repo.get(run.id)
    assert fetched.id == run.id


def test_run_repo_cycle_id_user_id_unique(db_session: Session, user: User) -> None:
    """cycle_id + user_id 复合 UNIQUE — 同 cycle 同 user 不能两条 run。"""
    repo = MonitoringRunRepo(db_session)
    cycle = str(uuid4())
    repo.create(user_id=user.id, cycle_id=cycle, trigger_type="cron", started_at=datetime.utcnow())
    db_session.commit()
    with pytest.raises(IntegrityError):
        repo.create(
            user_id=user.id, cycle_id=cycle, trigger_type="cron", started_at=datetime.utcnow()
        )
        db_session.commit()


def test_signal_repo_create_and_list_by_run(db_session: Session, user: User) -> None:
    run_repo = MonitoringRunRepo(db_session)
    sig_repo = MonitoringSignalRepo(db_session)
    run = run_repo.create(
        user_id=user.id, cycle_id=str(uuid4()), trigger_type="cron", started_at=datetime.utcnow()
    )
    db_session.flush()
    sig_repo.create(
        run_id=run.id,
        user_id=user.id,
        ts_code="600519.SH",
        rule_name="price_anomaly",
        level="yellow",
        explanation="-6%",
    )
    sig_repo.create(
        run_id=run.id,
        user_id=user.id,
        ts_code="600519.SH",
        rule_name="announcement",
        level="green",
        explanation="ok",
    )
    db_session.commit()
    signals = sig_repo.list_by_run(run.id)
    assert len(signals) == 2


def test_alert_repo_create_default_pending_then_update_to_ready(
    db_session: Session, user: User
) -> None:
    run_repo = MonitoringRunRepo(db_session)
    alert_repo = MonitoringAlertRepo(db_session)
    run = run_repo.create(
        user_id=user.id, cycle_id=str(uuid4()), trigger_type="cron", started_at=datetime.utcnow()
    )
    db_session.flush()
    alert = alert_repo.create(
        run_id=run.id,
        user_id=user.id,
        ts_code="600519.SH",
        alert_level="red",
        report_json={},
    )
    db_session.commit()
    assert alert.detail_status == "pending"

    alert_repo.update_detail(
        alert.id, status="ready", report_json={"a": 1}, report_markdown="# detail"
    )
    db_session.commit()
    fetched = alert_repo.get(alert.id)
    assert fetched.detail_status == "ready"
    assert fetched.report_markdown == "# detail"


def test_alert_repo_update_detail_to_failed(db_session: Session, user: User) -> None:
    run_repo = MonitoringRunRepo(db_session)
    alert_repo = MonitoringAlertRepo(db_session)
    run = run_repo.create(
        user_id=user.id, cycle_id=str(uuid4()), trigger_type="cron", started_at=datetime.utcnow()
    )
    db_session.flush()
    alert = alert_repo.create(
        run_id=run.id, user_id=user.id, ts_code="600519.SH", alert_level="red", report_json={}
    )
    db_session.commit()
    alert_repo.update_detail(alert.id, status="failed", error_message="LLM rate limit")
    db_session.commit()
    fetched = alert_repo.get(alert.id)
    assert fetched.detail_status == "failed"
    assert "rate limit" in fetched.error_message


def test_alert_repo_list_for_user_scoped(db_session: Session) -> None:
    run_repo = MonitoringRunRepo(db_session)
    alert_repo = MonitoringAlertRepo(db_session)

    u1 = make_user(db_session)
    u2 = make_user(db_session)

    r1 = run_repo.create(
        user_id=u1.id, cycle_id=str(uuid4()), trigger_type="cron", started_at=datetime.utcnow()
    )
    r2 = run_repo.create(
        user_id=u2.id, cycle_id=str(uuid4()), trigger_type="cron", started_at=datetime.utcnow()
    )
    db_session.flush()
    alert_repo.create(run_id=r1.id, user_id=u1.id, ts_code="A", alert_level="red", report_json={})
    alert_repo.create(run_id=r2.id, user_id=u2.id, ts_code="B", alert_level="red", report_json={})
    db_session.commit()

    u1_alerts = alert_repo.list_for_user(u1.id)
    assert len(u1_alerts) == 1
    assert u1_alerts[0].ts_code == "A"


def test_notification_repo_create(db_session: Session, user: User) -> None:
    run_repo = MonitoringRunRepo(db_session)
    alert_repo = MonitoringAlertRepo(db_session)
    notif_repo = NotificationRepo(db_session)
    run = run_repo.create(
        user_id=user.id, cycle_id=str(uuid4()), trigger_type="cron", started_at=datetime.utcnow()
    )
    db_session.flush()
    alert = alert_repo.create(
        run_id=run.id, user_id=user.id, ts_code="600519.SH", alert_level="red", report_json={}
    )
    db_session.flush()
    notif = notif_repo.create(alert_id=alert.id, channel="in_app", send_status="sent")
    db_session.commit()
    assert notif.alert_id == alert.id
