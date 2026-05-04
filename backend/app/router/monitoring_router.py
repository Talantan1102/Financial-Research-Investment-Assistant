"""REST API for B-3 monitoring engine (customers / runs / alerts / config).

Endpoints:
  GET  /api/monitoring/customers           list all customers
  POST /api/monitoring/customers           create a customer
  PUT  /api/monitoring/customers/{cid}     update a customer
  DELETE /api/monitoring/customers/{cid}   delete a customer
  GET  /api/monitoring/runs                list runs (optionally filtered by customer_id)
  POST /api/monitoring/runs                trigger a manual scan (background task)
  GET  /api/monitoring/alerts              list alerts (optionally filtered)
  GET  /api/monitoring/alerts/{aid}        get alert detail (with LEFT JOIN notifications)
  GET  /api/monitoring/config              get default thresholds + scheduler config

Carryover (Task 15 instructions):
  - Alert detail uses LEFT JOIN on notifications so that an alert row without
    a notification row still returns 200 (not 404 / crash).
  - All Pydantic models use ConfigDict(extra="forbid").
  - MonitoringService DI is FastAPI-native (injected via Depends, not global state
    in the router itself — see get_monitoring_service() in app_main.py).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])

# Path to the monitoring sqlite DB.  Resolved from this file's location:
# backend/app/router/monitoring_router.py  → parents[1] = backend/app → parents[2] = backend
# → backend/data/monitoring.sqlite
_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "monitoring.sqlite"


# ---------------------------------------------------------------------------
# MonitoringService dependency override point
#
# app_main.py calls install_monitoring_service_factory(get_monitoring_service)
# after building the real singleton.  Tests patch _get_monitoring_service_fn
# directly via monkeypatch.setattr(monitoring_router, "_get_monitoring_service_fn", ...)
# without ever importing app_main (which has a legacy `from router import ...`
# top-level import that breaks in the test environment).
# ---------------------------------------------------------------------------


def _default_monitoring_service_fn() -> Any:
    raise RuntimeError(
        "MonitoringService not initialised.  "
        "Call monitoring_router.install_monitoring_service_factory() from app startup."
    )


_get_monitoring_service_fn: Any = _default_monitoring_service_fn


def install_monitoring_service_factory(factory: Any) -> None:
    """Called by app_main to wire the real MonitoringService factory."""
    global _get_monitoring_service_fn
    _get_monitoring_service_fn = factory


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class CustomerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ts_code: str
    name: str
    industry: str
    enabled: bool = True
    thresholds_override: dict[str, float] | None = None


class CustomerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    industry: str | None = None
    enabled: bool | None = None
    thresholds_override: dict[str, float] | None = None


class CustomerOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    ts_code: str
    name: str
    industry: str
    enabled: bool
    thresholds_override: dict[str, float] | None = None


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_ids: list[str] = Field(..., min_length=1)


class RunOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    customer_id: str
    trigger_type: str
    started_at: str | None
    finished_at: str | None
    status: str


class AlertSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    run_id: str
    customer_id: str
    alert_level: str
    created_at: str | None


class NotificationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    channel: str
    recipient: str | None
    send_status: str
    error_message: str | None = None


class AlertDetailOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    run_id: str
    customer_id: str
    alert_level: str
    report_json: dict[str, Any]
    report_markdown: str | None
    escalated: bool
    escalation_status: str | None
    deep_dive_text: str | None
    created_at: str | None
    notifications: list[NotificationOut]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with foreign-key enforcement on."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_db_exists() -> None:
    """Create the monitoring DB tables if the file doesn't exist yet.

    This is a safety fallback for environments where init_monitoring_tables
    hasn't been called explicitly (e.g., fresh unit-test tmp dir that
    bypasses app lifespan).  In production the tables are created by
    app_main.py on startup.
    """
    if not _DB_PATH.exists():
        from app.scripts.init_monitoring_tables import init_monitoring_tables

        init_monitoring_tables(_DB_PATH)


# ---------------------------------------------------------------------------
# Customer endpoints
# ---------------------------------------------------------------------------


@router.get("/customers", response_model=dict[str, list[CustomerOut]])
def list_customers() -> dict[str, list[CustomerOut]]:
    """List all monitored customers."""
    _ensure_db_exists()
    with _connect(_DB_PATH) as conn:
        rows = conn.execute(
            "SELECT id, ts_code, name, industry, enabled, thresholds_override "
            "FROM monitoring_customers ORDER BY created_at DESC"
        ).fetchall()
    customers = [
        CustomerOut(
            id=r[0],
            ts_code=r[1],
            name=r[2],
            industry=r[3],
            enabled=bool(r[4]),
            thresholds_override=json.loads(r[5]) if r[5] else None,
        )
        for r in rows
    ]
    return {"customers": customers}


@router.post("/customers", response_model=CustomerOut, status_code=201)
def create_customer(payload: CustomerCreate) -> CustomerOut:
    """Create a new monitored customer."""
    _ensure_db_exists()
    cid = str(uuid.uuid4())
    with _connect(_DB_PATH) as conn:
        try:
            conn.execute(
                "INSERT INTO monitoring_customers "
                "(id, ts_code, name, industry, enabled, thresholds_override) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    cid,
                    payload.ts_code,
                    payload.name,
                    payload.industry,
                    1 if payload.enabled else 0,
                    json.dumps(payload.thresholds_override)
                    if payload.thresholds_override
                    else None,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="ts_code already exists") from exc
    return CustomerOut(
        id=cid,
        ts_code=payload.ts_code,
        name=payload.name,
        industry=payload.industry,
        enabled=payload.enabled,
        thresholds_override=payload.thresholds_override,
    )


@router.put("/customers/{cid}", response_model=CustomerOut)
def update_customer(cid: str, payload: CustomerUpdate) -> CustomerOut:
    """Update a monitored customer's fields."""
    _ensure_db_exists()
    with _connect(_DB_PATH) as conn:
        row = conn.execute(
            "SELECT id, ts_code, name, industry, enabled, thresholds_override "
            "FROM monitoring_customers WHERE id = ?",
            (cid,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="customer not found")

        new_name = payload.name if payload.name is not None else row[2]
        new_industry = payload.industry if payload.industry is not None else row[3]
        new_enabled = payload.enabled if payload.enabled is not None else bool(row[4])
        new_thresholds_override: dict[str, float] | None
        if payload.thresholds_override is not None:
            new_thresholds_override = payload.thresholds_override
        else:
            new_thresholds_override = json.loads(row[5]) if row[5] else None

        conn.execute(
            "UPDATE monitoring_customers "
            "SET name=?, industry=?, enabled=?, thresholds_override=?, "
            "    updated_at=CURRENT_TIMESTAMP "
            "WHERE id=?",
            (
                new_name,
                new_industry,
                1 if new_enabled else 0,
                json.dumps(new_thresholds_override) if new_thresholds_override else None,
                cid,
            ),
        )
    return CustomerOut(
        id=cid,
        ts_code=row[1],
        name=new_name,
        industry=new_industry,
        enabled=new_enabled,
        thresholds_override=new_thresholds_override,
    )


@router.delete("/customers/{cid}", status_code=204)
def delete_customer(cid: str) -> None:
    """Delete a monitored customer."""
    _ensure_db_exists()
    with _connect(_DB_PATH) as conn:
        cur = conn.execute("DELETE FROM monitoring_customers WHERE id = ?", (cid,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="customer not found")


# ---------------------------------------------------------------------------
# Run endpoints
# ---------------------------------------------------------------------------


@router.get("/runs", response_model=dict[str, list[RunOut]])
def list_runs(customer_id: str | None = None) -> dict[str, list[RunOut]]:
    """List monitoring runs, optionally filtered by customer_id."""
    _ensure_db_exists()
    with _connect(_DB_PATH) as conn:
        if customer_id:
            rows = conn.execute(
                "SELECT id, customer_id, trigger_type, started_at, finished_at, status "
                "FROM monitoring_runs "
                "WHERE customer_id = ? "
                "ORDER BY started_at DESC",
                (customer_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, customer_id, trigger_type, started_at, finished_at, status "
                "FROM monitoring_runs "
                "ORDER BY started_at DESC LIMIT 100"
            ).fetchall()
    return {
        "runs": [
            RunOut(
                id=r[0],
                customer_id=r[1],
                trigger_type=r[2],
                started_at=r[3],
                finished_at=r[4],
                status=r[5],
            )
            for r in rows
        ]
    }


@router.post("/runs", status_code=202)
async def trigger_scan(payload: RunRequest, bg: BackgroundTasks) -> dict[str, Any]:
    """Trigger a manual scan for the given customer IDs.

    The actual scan runs as a FastAPI background task and returns immediately
    with status="queued".  The caller can poll GET /runs to watch progress.

    MonitoringService is resolved via _get_monitoring_service() which is
    a module-level override point.  app_main.py installs the real factory;
    tests patch monitoring_router._get_monitoring_service_fn directly.
    """
    svc = _get_monitoring_service_fn()

    async def _run() -> None:
        try:
            await svc.run_scan(payload.customer_ids, trigger_type="manual")
        except Exception as exc:
            logger.error("monitoring run_scan failed in background task: %s", exc, exc_info=True)

    bg.add_task(_run)
    return {"customer_ids": payload.customer_ids, "status": "queued"}


# ---------------------------------------------------------------------------
# Alert endpoints
# ---------------------------------------------------------------------------


@router.get("/alerts", response_model=dict[str, list[AlertSummaryOut]])
def list_alerts(
    customer_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, list[AlertSummaryOut]]:
    """List alert summaries (no full report_json to keep response small)."""
    _ensure_db_exists()
    with _connect(_DB_PATH) as conn:
        if customer_id:
            rows = conn.execute(
                "SELECT id, run_id, customer_id, alert_level, created_at "
                "FROM monitoring_alerts "
                "WHERE customer_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (customer_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, run_id, customer_id, alert_level, created_at "
                "FROM monitoring_alerts "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return {
        "alerts": [
            AlertSummaryOut(
                id=r[0],
                run_id=r[1],
                customer_id=r[2],
                alert_level=r[3],
                created_at=r[4],
            )
            for r in rows
        ]
    }


@router.get("/alerts/{aid}", response_model=AlertDetailOut)
def get_alert(aid: str) -> AlertDetailOut:
    """Get full alert detail including report JSON and associated notifications.

    Uses LEFT JOIN on the notifications table so that an alert without any
    notification row (e.g. if _send_notifications raised) still returns 200.
    (Carryover: Task 15 alert-notification atomicity gap fix.)
    """
    _ensure_db_exists()
    with _connect(_DB_PATH) as conn:
        # Alert row
        alert_row = conn.execute(
            "SELECT id, run_id, customer_id, alert_level, report_json, report_markdown, "
            "       escalated, escalation_status, deep_dive_text, created_at "
            "FROM monitoring_alerts WHERE id = ?",
            (aid,),
        ).fetchone()
        if alert_row is None:
            raise HTTPException(status_code=404, detail="alert not found")

        # LEFT JOIN notifications — returns [] if no notification rows
        notif_rows = conn.execute(
            "SELECT id, channel, recipient, send_status, error_message "
            "FROM notifications WHERE alert_id = ?",
            (aid,),
        ).fetchall()

    notifications = [
        NotificationOut(
            id=nr[0],
            channel=nr[1],
            recipient=nr[2],
            send_status=nr[3],
            error_message=nr[4],
        )
        for nr in notif_rows
    ]

    return AlertDetailOut(
        id=alert_row[0],
        run_id=alert_row[1],
        customer_id=alert_row[2],
        alert_level=alert_row[3],
        report_json=json.loads(alert_row[4]),
        report_markdown=alert_row[5],
        escalated=bool(alert_row[6]),
        escalation_status=alert_row[7],
        deep_dive_text=alert_row[8],
        created_at=alert_row[9],
        notifications=notifications,
    )


# ---------------------------------------------------------------------------
# Config endpoint
# ---------------------------------------------------------------------------


@router.get("/config")
def get_config() -> dict[str, Any]:
    """Return current default thresholds and scheduler configuration."""
    from app.services.monitoring.signal_rules.defaults import DEFAULT_THRESHOLDS

    return {
        "scan_time": "16:30",
        "scan_timezone": "Asia/Shanghai",
        "daily_budget_cny": 10.0,
        "thresholds": DEFAULT_THRESHOLDS,
    }
