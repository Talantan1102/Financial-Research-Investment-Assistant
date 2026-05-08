"""generate_detail_card task — autoretry + state machine.

Spec § 5.1 LLM 失败 autoretry max=2; § 3.2 state machine; § 5.2 acks_late requires idempotency.
"""

from __future__ import annotations

import datetime as _dt
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from app.models.monitoring import (
    DetailStatus,
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
def session() -> Session:
    # 项目约定:不全量 create_all(其他模型有 JSONB 在 sqlite 不可编译);只建本测试用到的表
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    MonitoringRun.__table__.create(engine)
    MonitoringSignal.__table__.create(engine)
    MonitoringAlert.__table__.create(engine)
    Notification.__table__.create(engine)
    with Session(engine) as s:
        yield s


def _make_alert(session: Session) -> str:
    uid = uuid4().hex[:8]
    user = User(
        id=str(uuid4()),
        username=f"user-{uid}",
        email=f"u-{uid}@t",
        hashed_password="x",
        is_active=True,
    )
    session.add(user)
    session.flush()
    run = MonitoringRun(
        id=str(uuid4()),
        user_id=user.id,
        cycle_id=str(uuid4()),
        trigger_type="cron",
        started_at=_dt.datetime.utcnow(),
        status="success",
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
    return alert.id


def test_generate_detail_card_success_sets_ready(session):
    alert_id = _make_alert(session)

    mock_writer = MagicMock()
    mock_writer.alert_writer = AsyncMock(
        return_value={
            "json": {"summary": "茅台 -6% 因为 X"},
            "markdown": "# 异动\n茅台 -6% 因为 X",
        }
    )

    with (
        patch("app.tasks.monitoring._build_writer", return_value=mock_writer),
        patch("app.tasks.monitoring._get_session", return_value=session),
    ):
        from app.tasks.monitoring import generate_detail_card

        generate_detail_card.apply(args=[alert_id]).get()

    refreshed = session.query(MonitoringAlert).filter_by(id=alert_id).one()
    assert refreshed.detail_status == DetailStatus.READY
    assert refreshed.report_markdown.startswith("# 异动")


def test_generate_detail_card_llm_failure_after_retries_sets_failed(session):
    alert_id = _make_alert(session)

    mock_writer = MagicMock()
    mock_writer.alert_writer = AsyncMock(side_effect=Exception("LLM rate limit"))

    with (
        patch("app.tasks.monitoring._build_writer", return_value=mock_writer),
        patch("app.tasks.monitoring._get_session", return_value=session),
    ):
        from app.tasks.monitoring import generate_detail_card

        # eager mode + propagates → 异常 raise(autoretry 在 eager 不真的 retry,直接到最大次数)
        with pytest.raises(Exception, match="rate limit"):
            generate_detail_card.apply(args=[alert_id]).get()

    refreshed = session.query(MonitoringAlert).filter_by(id=alert_id).one()
    # autoretry 全部失败后 final state
    assert refreshed.detail_status == DetailStatus.FAILED
    assert "rate limit" in (refreshed.error_message or "")


def test_generate_detail_card_idempotent_on_retry(session):
    """重复跑同一 alert_id 不会 corrupt state(spec § 5.2 acks_late requires idempotency)."""
    alert_id = _make_alert(session)

    mock_writer = MagicMock()
    mock_writer.alert_writer = AsyncMock(return_value={"json": {"a": 1}, "markdown": "# x"})

    with (
        patch("app.tasks.monitoring._build_writer", return_value=mock_writer),
        patch("app.tasks.monitoring._get_session", return_value=session),
    ):
        from app.tasks.monitoring import generate_detail_card

        generate_detail_card.apply(args=[alert_id]).get()
        generate_detail_card.apply(args=[alert_id]).get()  # 第二次 — 同 UPDATE

    alerts = session.query(MonitoringAlert).filter_by(id=alert_id).all()
    assert len(alerts) == 1  # 还是同一行
    assert alerts[0].detail_status == DetailStatus.READY
