"""Monitoring repos — sqlite-override + cycle_id UNIQUE."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from uuid import uuid4

import pytest
from app.models.monitoring import (
    MonitoringAlert,
    MonitoringRun,
    MonitoringSignal,
    Notification,
)
from app.models.user import User
from app.services.monitoring.repositories import (
    MonitoringAlertRepo,
    MonitoringRunRepo,
    MonitoringSignalRepo,
    NotificationRepo,
)
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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


@pytest.fixture
def user(session: Session) -> User:
    return make_user(session)


def test_run_repo_create_and_get(session: Session, user: User) -> None:
    repo = MonitoringRunRepo(session)
    run = repo.create(
        user_id=user.id,
        cycle_id=str(uuid4()),
        trigger_type="cron",
        started_at=datetime.utcnow(),
    )
    fetched = repo.get(run.id)
    assert fetched.id == run.id


def test_run_repo_cycle_id_user_id_unique(session: Session, user: User) -> None:
    """cycle_id + user_id 复合 UNIQUE — 同 cycle 同 user 不能两条 run。"""
    repo = MonitoringRunRepo(session)
    cycle = str(uuid4())
    repo.create(user_id=user.id, cycle_id=cycle, trigger_type="cron", started_at=datetime.utcnow())
    session.commit()
    with pytest.raises(IntegrityError):
        repo.create(
            user_id=user.id, cycle_id=cycle, trigger_type="cron", started_at=datetime.utcnow()
        )
        session.commit()


def test_signal_repo_create_and_list_by_run(session: Session, user: User) -> None:
    run_repo = MonitoringRunRepo(session)
    sig_repo = MonitoringSignalRepo(session)
    run = run_repo.create(
        user_id=user.id, cycle_id=str(uuid4()), trigger_type="cron", started_at=datetime.utcnow()
    )
    session.flush()
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
    session.commit()
    signals = sig_repo.list_by_run(run.id)
    assert len(signals) == 2


def test_alert_repo_create_default_pending_then_update_to_ready(
    session: Session, user: User
) -> None:
    run_repo = MonitoringRunRepo(session)
    alert_repo = MonitoringAlertRepo(session)
    run = run_repo.create(
        user_id=user.id, cycle_id=str(uuid4()), trigger_type="cron", started_at=datetime.utcnow()
    )
    session.flush()
    alert = alert_repo.create(
        run_id=run.id,
        user_id=user.id,
        ts_code="600519.SH",
        alert_level="red",
        report_json={},
    )
    session.commit()
    assert alert.detail_status == "pending"

    alert_repo.update_detail(
        alert.id, status="ready", report_json={"a": 1}, report_markdown="# detail"
    )
    session.commit()
    fetched = alert_repo.get(alert.id)
    assert fetched.detail_status == "ready"
    assert fetched.report_markdown == "# detail"


def test_alert_repo_update_detail_to_failed(session: Session, user: User) -> None:
    run_repo = MonitoringRunRepo(session)
    alert_repo = MonitoringAlertRepo(session)
    run = run_repo.create(
        user_id=user.id, cycle_id=str(uuid4()), trigger_type="cron", started_at=datetime.utcnow()
    )
    session.flush()
    alert = alert_repo.create(
        run_id=run.id, user_id=user.id, ts_code="600519.SH", alert_level="red", report_json={}
    )
    session.commit()
    alert_repo.update_detail(alert.id, status="failed", error_message="LLM rate limit")
    session.commit()
    fetched = alert_repo.get(alert.id)
    assert fetched.detail_status == "failed"
    assert "rate limit" in fetched.error_message


def test_alert_repo_list_for_user_scoped(session: Session) -> None:
    run_repo = MonitoringRunRepo(session)
    alert_repo = MonitoringAlertRepo(session)

    u1 = make_user(session)
    u2 = make_user(session)

    r1 = run_repo.create(
        user_id=u1.id, cycle_id=str(uuid4()), trigger_type="cron", started_at=datetime.utcnow()
    )
    r2 = run_repo.create(
        user_id=u2.id, cycle_id=str(uuid4()), trigger_type="cron", started_at=datetime.utcnow()
    )
    session.flush()
    alert_repo.create(run_id=r1.id, user_id=u1.id, ts_code="A", alert_level="red", report_json={})
    alert_repo.create(run_id=r2.id, user_id=u2.id, ts_code="B", alert_level="red", report_json={})
    session.commit()

    u1_alerts = alert_repo.list_for_user(u1.id)
    assert len(u1_alerts) == 1
    assert u1_alerts[0].ts_code == "A"


def test_notification_repo_create(session: Session, user: User) -> None:
    run_repo = MonitoringRunRepo(session)
    alert_repo = MonitoringAlertRepo(session)
    notif_repo = NotificationRepo(session)
    run = run_repo.create(
        user_id=user.id, cycle_id=str(uuid4()), trigger_type="cron", started_at=datetime.utcnow()
    )
    session.flush()
    alert = alert_repo.create(
        run_id=run.id, user_id=user.id, ts_code="600519.SH", alert_level="red", report_json={}
    )
    session.flush()
    notif = notif_repo.create(alert_id=alert.id, channel="in_app", send_status="sent")
    session.commit()
    assert notif.alert_id == alert.id
