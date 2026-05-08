"""REST API for v1.0 monitoring engine.

Endpoints:
  GET  /api/monitoring/signals               list user's alerts (paginated)
  GET  /api/monitoring/signals/{aid}/detail  single alert detail (with markdown)
  POST /api/monitoring/refresh               manual detection_cycle for current user

Spec § 4.6 /monitoring/refresh + § 7.3 老 endpoint 退役.

Note(Task 13): the v0.x endpoints (customers / runs / scan / alerts / config)
have been removed.  The full retirement (deleting MonitoringScheduler /
MonitoringService / init_monitoring_tables) is Task 14.  This file is the
final shape; install_monitoring_service_factory() is intentionally kept as a
no-op shim so that existing app_main wiring keeps importing without error
until Task 14 lands.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.router.auth_router import get_current_user_required
from app.services.monitoring.repositories import MonitoringAlertRepo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


# ---------------------------------------------------------------------------
# Legacy DI shim — Task 14 removes app_main's install_monitoring_service_factory
# call entirely.  Until then, keep a no-op so import + startup don't break.
# ---------------------------------------------------------------------------


def install_monitoring_service_factory(factory: Any) -> None:  # pragma: no cover
    """No-op shim retained for app_main compatibility — removed in Task 14."""
    return None


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class SignalSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    run_id: str
    ts_code: str
    alert_level: str
    detail_status: str
    created_at: str | None


class SignalDetailOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    ts_code: str
    alert_level: str
    detail_status: str
    report_json: dict[str, Any]
    report_markdown: str | None
    error_message: str | None
    created_at: str | None


class RefreshResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    status: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/signals", response_model=dict[str, list[SignalSummaryOut]])
def list_signals(
    limit: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_required),
) -> dict[str, list[SignalSummaryOut]]:
    """返回 current user 的 alert 列表(按 created_at DESC)."""
    repo = MonitoringAlertRepo(db)
    alerts = repo.list_for_user(str(user.id), limit=limit)
    return {
        "signals": [
            SignalSummaryOut(
                id=a.id,
                run_id=a.run_id,
                ts_code=a.ts_code,
                alert_level=a.alert_level,
                detail_status=a.detail_status,
                created_at=a.created_at.isoformat() if a.created_at else None,
            )
            for a in alerts
        ]
    }


@router.get("/signals/{aid}/detail", response_model=SignalDetailOut)
def get_signal_detail(
    aid: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_required),
) -> SignalDetailOut:
    """单条 alert 详情(包括 markdown)。cross-user 隔离 → 404."""
    repo = MonitoringAlertRepo(db)
    alert = repo.get(aid)
    if alert is None or str(alert.user_id) != str(user.id):
        raise HTTPException(status_code=404, detail="alert not found")
    return SignalDetailOut(
        id=alert.id,
        ts_code=alert.ts_code,
        alert_level=alert.alert_level,
        detail_status=alert.detail_status,
        report_json=alert.report_json or {},
        report_markdown=alert.report_markdown,
        error_message=alert.error_message,
        created_at=alert.created_at.isoformat() if alert.created_at else None,
    )


@router.post("/refresh", response_model=RefreshResponse, status_code=202)
def refresh_for_current_user(
    user: User = Depends(get_current_user_required),
) -> RefreshResponse:
    """手动触发 detection cycle for current user(spec § 4.6)."""
    from app.tasks.monitoring import detection_cycle

    result = detection_cycle.delay(user_filter=str(user.id))
    return RefreshResponse(task_id=str(result.id), status="queued")
