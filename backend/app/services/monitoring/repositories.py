"""Monitoring table repositories — thin SQLAlchemy wrappers."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.monitoring import (
    DetailStatus,
    MonitoringAlert,
    MonitoringRun,
    MonitoringSignal,
    Notification,
)


class MonitoringRunRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        user_id: str | None,
        cycle_id: str,
        trigger_type: str,
        started_at: datetime,
        status: str = "running",
    ) -> MonitoringRun:
        run = MonitoringRun(
            id=str(uuid4()),
            user_id=user_id,
            cycle_id=cycle_id,
            trigger_type=trigger_type,
            started_at=started_at,
            status=status,
        )
        self._session.add(run)
        self._session.flush()
        return run

    def get(self, run_id: str) -> MonitoringRun | None:
        return self._session.get(MonitoringRun, run_id)

    def mark_finished(self, run_id: str, status: str, error: str | None = None) -> None:
        run = self.get(run_id)
        if run is None:
            return
        run.finished_at = datetime.utcnow()
        run.status = status
        run.error_message = error


class MonitoringSignalRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        run_id: str,
        user_id: str,
        ts_code: str,
        rule_name: str,
        level: str,
        detected_value: str | None = None,
        threshold: str | None = None,
        explanation: str | None = None,
        raw_data_ref: dict[str, Any] | None = None,
    ) -> MonitoringSignal:
        sig = MonitoringSignal(
            id=str(uuid4()),
            run_id=run_id,
            user_id=user_id,
            ts_code=ts_code,
            rule_name=rule_name,
            level=level,
            detected_value=detected_value,
            threshold=threshold,
            explanation=explanation,
            raw_data_ref=raw_data_ref,
        )
        self._session.add(sig)
        self._session.flush()
        return sig

    def list_by_run(self, run_id: str) -> list[MonitoringSignal]:
        return list(
            self._session.query(MonitoringSignal)
            .filter_by(run_id=run_id)
            .order_by(MonitoringSignal.created_at)
            .all()
        )


class MonitoringAlertRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        run_id: str,
        user_id: str,
        ts_code: str,
        alert_level: str,
        report_json: dict[str, Any],
        detail_status: str = DetailStatus.PENDING,
    ) -> MonitoringAlert:
        alert = MonitoringAlert(
            id=str(uuid4()),
            run_id=run_id,
            user_id=user_id,
            ts_code=ts_code,
            alert_level=alert_level,
            report_json=report_json,
            detail_status=detail_status,
        )
        self._session.add(alert)
        self._session.flush()
        return alert

    def get(self, alert_id: str) -> MonitoringAlert | None:
        return self._session.get(MonitoringAlert, alert_id)

    def update_detail(
        self,
        alert_id: str,
        *,
        status: str,
        report_json: dict[str, Any] | None = None,
        report_markdown: str | None = None,
        error_message: str | None = None,
    ) -> None:
        alert = self.get(alert_id)
        if alert is None:
            return
        alert.detail_status = status
        if report_json is not None:
            alert.report_json = report_json
        if report_markdown is not None:
            alert.report_markdown = report_markdown
        if error_message is not None:
            alert.error_message = error_message

    def list_for_user(self, user_id: str, limit: int = 50) -> list[MonitoringAlert]:
        return list(
            self._session.query(MonitoringAlert)
            .filter_by(user_id=user_id)
            .order_by(MonitoringAlert.created_at.desc())
            .limit(limit)
            .all()
        )


class NotificationRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        alert_id: str,
        channel: str,
        send_status: str,
        recipient: str | None = None,
        error_message: str | None = None,
    ) -> Notification:
        notif = Notification(
            id=str(uuid4()),
            alert_id=alert_id,
            channel=channel,
            send_status=send_status,
            recipient=recipient,
            error_message=error_message,
            sent_at=datetime.utcnow() if send_status == "sent" else None,
        )
        self._session.add(notif)
        self._session.flush()
        return notif
