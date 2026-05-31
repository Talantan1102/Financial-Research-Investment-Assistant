"""daily_full_scan + cleanup_old."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from app.models.monitoring import (
    MonitoringRun,
)
from app.models.user import User
from sqlalchemy.orm import Session


@pytest.fixture(autouse=True)
def celery_eager(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    monkeypatch.setenv("CELERY_TASK_EAGER_PROPAGATES", "1")


def test_daily_full_scan_dispatches_detection_cycle(db_session: Session) -> None:
    """C59: daily_full_scan 应异步 .delay() 派发(不 .apply() 同步阻塞 worker),
    并返回真实 task_id。"""
    called = []
    task_id = str(uuid4())

    def _fake_delay(*args, **kwargs):
        called.append(True)
        from celery.result import EagerResult

        return EagerResult(task_id, {}, "SUCCESS")

    with patch("app.tasks.monitoring.detection_cycle.delay", side_effect=_fake_delay):
        from app.tasks.monitoring import daily_full_scan

        res = daily_full_scan.apply().get()

    assert len(called) == 1
    assert res["status"] == "dispatched"
    assert res["task_id"] == task_id


def test_cleanup_old_deletes_runs_older_than_7_days(db_session: Session) -> None:
    uid = uuid4().hex[:8]
    user = User(
        id=str(uuid4()),
        username=f"u-{uid}",
        email=f"u-{uid}@t",
        hashed_password="x",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    old_run = MonitoringRun(
        id=str(uuid4()),
        user_id=user.id,
        cycle_id=str(uuid4()),
        trigger_type="cron",
        started_at=datetime.utcnow() - timedelta(days=10),
        status="success",
    )
    new_run = MonitoringRun(
        id=str(uuid4()),
        user_id=user.id,
        cycle_id=str(uuid4()),
        trigger_type="cron",
        started_at=datetime.utcnow() - timedelta(days=2),
        status="success",
    )
    db_session.add_all([old_run, new_run])
    db_session.commit()

    with patch("app.tasks.monitoring._get_session", return_value=db_session):
        from app.tasks.monitoring import cleanup_old

        cleanup_old.apply(kwargs={"days": 7}).get()

    remaining = db_session.query(MonitoringRun).filter_by(user_id=user.id).all()
    assert len(remaining) == 1
    assert remaining[0].id == new_run.id
