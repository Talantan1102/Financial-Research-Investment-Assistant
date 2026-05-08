"""daily_full_scan + cleanup_old."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from app.models.monitoring import (
    MonitoringAlert,
    MonitoringRun,
    MonitoringSignal,
    Notification,
)
from app.models.user import User
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture(autouse=True)
def celery_eager(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    monkeypatch.setenv("CELERY_TASK_EAGER_PROPAGATES", "1")


@pytest.fixture
def session() -> Generator[Session, None, None]:
    # 项目约定:不全量 create_all(其他模型有 JSONB 在 sqlite 不可编译);只建本测试用到的表
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    MonitoringRun.__table__.create(engine)
    MonitoringSignal.__table__.create(engine)
    MonitoringAlert.__table__.create(engine)
    Notification.__table__.create(engine)
    # expire_on_commit=False:impl 内 session.close() 后,test fixture 端
    # 仍引用同一 session 做 assertion;不关此 flag 会触发 DetachedInstanceError。
    with Session(engine, expire_on_commit=False) as s:
        yield s


def test_daily_full_scan_calls_detection_cycle(session):
    called = []

    def _fake(*args, **kwargs):
        called.append(True)
        from celery.result import EagerResult

        return EagerResult(str(uuid4()), {}, "SUCCESS")

    with patch("app.tasks.monitoring.detection_cycle.apply", side_effect=_fake):
        from app.tasks.monitoring import daily_full_scan

        daily_full_scan.apply().get()

    assert len(called) == 1


def test_cleanup_old_deletes_runs_older_than_7_days(session):
    uid = uuid4().hex[:8]
    user = User(
        id=str(uuid4()),
        username=f"u-{uid}",
        email=f"u-{uid}@t",
        hashed_password="x",
        is_active=True,
    )
    session.add(user)
    session.flush()

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
    session.add_all([old_run, new_run])
    session.commit()

    with patch("app.tasks.monitoring._get_session", return_value=session):
        from app.tasks.monitoring import cleanup_old

        cleanup_old.apply(kwargs={"days": 7}).get()

    remaining = session.query(MonitoringRun).all()
    assert len(remaining) == 1
    assert remaining[0].id == new_run.id
