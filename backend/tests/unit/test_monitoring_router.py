"""Unit tests for monitoring_router endpoints.

Tests use a minimal FastAPI app with only the monitoring router mounted,
and a tmp-path sqlite DB injected via monkeypatch.  This avoids importing
the full app_main (which pulls in legacy ``from router import ...`` that
requires PYTHONPATH to include backend/app/).

Carryover check (Task 15 instruction):
  - LEFT JOIN behaviour: alert detail must not 404 when no notification row exists.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_db(db_path: Path) -> None:
    """Create the 5 monitoring tables in a fresh sqlite DB."""
    from app.scripts.init_monitoring_tables import init_monitoring_tables

    init_monitoring_tables(db_path)


def _insert_customer(db_path: Path, cid: str, ts_code: str, name: str, industry: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO monitoring_customers (id, ts_code, name, industry) VALUES (?, ?, ?, ?)",
            (cid, ts_code, name, industry),
        )


def _insert_run(db_path: Path, run_id: str, cid: str, status: str = "success") -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO monitoring_runs "
            "(id, customer_id, trigger_type, started_at, finished_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, cid, "manual", "2026-05-04T10:00:00", "2026-05-04T10:01:00", status),
        )


def _insert_alert(
    db_path: Path, alert_id: str, run_id: str, cid: str, level: str = "yellow"
) -> None:
    report_json = json.dumps(
        {
            "alert_id": alert_id,
            "customer_id": cid,
            "ts_code": "600519.SH",
            "alert_level": level,
            "summary": "test summary",
            "signals": [],
        }
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO monitoring_alerts "
            "(id, run_id, customer_id, alert_level, report_json, report_markdown, escalated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (alert_id, run_id, cid, level, report_json, "# test", 0),
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    db = tmp_path / "monitoring.sqlite"
    _init_db(db)
    return db


def _make_mock_monitoring_service() -> MagicMock:
    """Return a MagicMock that satisfies MonitoringService.run_scan()."""
    svc = MagicMock()
    svc.run_scan = AsyncMock(return_value=["run-mock-1"])
    return svc


@pytest.fixture
def client(tmp_db: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Return a TestClient over a minimal FastAPI app with the monitoring router.

    - _DB_PATH in monitoring_router is patched to the tmp sqlite DB.
    - _get_monitoring_service_fn in monitoring_router is patched to a MagicMock
      so that the trigger_scan background task doesn't try to build the full
      dependency graph.  This avoids importing app_main (which has a legacy
      `from router import ...` top-level import that requires PYTHONPATH to
      include backend/app/).
    """
    import app.router.monitoring_router as mr

    monkeypatch.setattr(mr, "_DB_PATH", tmp_db)

    # Patch the DI override point in the router itself (not in app_main)
    mock_svc = _make_mock_monitoring_service()
    monkeypatch.setattr(mr, "_get_monitoring_service_fn", lambda: mock_svc)

    # Build a minimal FastAPI app with only the monitoring router
    test_app = FastAPI()
    test_app.include_router(mr.router)
    return TestClient(test_app)


# ---------------------------------------------------------------------------
# GET /api/monitoring/customers — empty
# ---------------------------------------------------------------------------


def test_list_customers_empty(client: TestClient) -> None:
    resp = client.get("/api/monitoring/customers")
    assert resp.status_code == 200
    assert resp.json() == {"customers": []}


# ---------------------------------------------------------------------------
# POST /api/monitoring/customers — create
# ---------------------------------------------------------------------------


def test_create_customer(client: TestClient) -> None:
    resp = client.post(
        "/api/monitoring/customers",
        json={"ts_code": "600519.SH", "name": "茅台", "industry": "消费"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["ts_code"] == "600519.SH"
    assert body["name"] == "茅台"
    assert "id" in body


def test_create_customer_duplicate_ts_code_returns_409(client: TestClient) -> None:
    payload = {"ts_code": "000001.SZ", "name": "平安银行", "industry": "金融"}
    resp1 = client.post("/api/monitoring/customers", json=payload)
    assert resp1.status_code == 201
    resp2 = client.post("/api/monitoring/customers", json=payload)
    assert resp2.status_code == 409


def test_create_customer_with_thresholds(client: TestClient) -> None:
    resp = client.post(
        "/api/monitoring/customers",
        json={
            "ts_code": "601318.SH",
            "name": "中国平安",
            "industry": "保险",
            "thresholds_override": {"financial_ratio.red_debt_ratio_abs": 85.0},
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["thresholds_override"] == {"financial_ratio.red_debt_ratio_abs": 85.0}


# ---------------------------------------------------------------------------
# PUT /api/monitoring/customers/{cid}
# ---------------------------------------------------------------------------


def test_update_customer_success(client: TestClient, tmp_db: Path) -> None:
    _insert_customer(tmp_db, "cid-upd", "002594.SZ", "比亚迪", "汽车")
    resp = client.put(
        "/api/monitoring/customers/cid-upd",
        json={"name": "比亚迪股份", "enabled": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "cid-upd"
    assert body["name"] == "比亚迪股份"
    assert body["enabled"] is False
    # unchanged fields survive
    assert body["industry"] == "汽车"


def test_update_customer_404(client: TestClient) -> None:
    resp = client.put(
        "/api/monitoring/customers/nonexistent",
        json={"name": "does not matter"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/monitoring/customers/{cid}
# ---------------------------------------------------------------------------


def test_delete_customer(client: TestClient, tmp_db: Path) -> None:
    _insert_customer(tmp_db, "cid-del", "000002.SZ", "万科", "地产")
    resp = client.delete("/api/monitoring/customers/cid-del")
    assert resp.status_code == 204


def test_delete_customer_not_found(client: TestClient) -> None:
    resp = client.delete("/api/monitoring/customers/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/monitoring/runs
# ---------------------------------------------------------------------------


def test_list_runs_for_customer(client: TestClient, tmp_db: Path) -> None:
    _insert_customer(tmp_db, "c1", "600519.SH", "茅台", "消费")
    _insert_run(tmp_db, "run-1", "c1")
    resp = client.get("/api/monitoring/runs?customer_id=c1")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["runs"]) == 1
    assert body["runs"][0]["id"] == "run-1"


def test_list_runs_no_filter(client: TestClient, tmp_db: Path) -> None:
    _insert_customer(tmp_db, "c2", "000001.SZ", "平安银行", "金融")
    _insert_run(tmp_db, "run-2", "c2")
    resp = client.get("/api/monitoring/runs")
    assert resp.status_code == 200
    assert len(resp.json()["runs"]) >= 1


# ---------------------------------------------------------------------------
# POST /api/monitoring/runs — manual trigger
# ---------------------------------------------------------------------------


def test_trigger_immediate_scan(client: TestClient) -> None:
    resp = client.post("/api/monitoring/runs", json={"customer_ids": ["c1"]})
    # Background task — returns 202
    assert resp.status_code in (200, 202)


# ---------------------------------------------------------------------------
# GET /api/monitoring/alerts
# ---------------------------------------------------------------------------


def test_list_alerts_empty(client: TestClient) -> None:
    resp = client.get("/api/monitoring/alerts")
    assert resp.status_code == 200
    assert resp.json() == {"alerts": []}


def test_list_alerts_with_data(client: TestClient, tmp_db: Path) -> None:
    _insert_customer(tmp_db, "c3", "601888.SH", "中国中免", "零售")
    _insert_run(tmp_db, "run-3", "c3")
    _insert_alert(tmp_db, "alert-3", "run-3", "c3", "red")
    resp = client.get("/api/monitoring/alerts")
    assert resp.status_code == 200
    alerts = resp.json()["alerts"]
    assert len(alerts) == 1
    assert alerts[0]["id"] == "alert-3"
    assert alerts[0]["alert_level"] == "red"


def test_list_alerts_filter_by_customer(client: TestClient, tmp_db: Path) -> None:
    _insert_customer(tmp_db, "c4", "600036.SH", "招商银行", "金融")
    _insert_run(tmp_db, "run-4", "c4")
    _insert_alert(tmp_db, "alert-4", "run-4", "c4", "yellow")
    resp = client.get("/api/monitoring/alerts?customer_id=c4")
    assert resp.status_code == 200
    assert len(resp.json()["alerts"]) == 1


# ---------------------------------------------------------------------------
# GET /api/monitoring/alerts/{aid}
# ---------------------------------------------------------------------------


def test_get_alert_detail_404_when_missing(client: TestClient) -> None:
    resp = client.get("/api/monitoring/alerts/nonexistent")
    assert resp.status_code == 404


def test_get_alert_detail_no_notification_row(client: TestClient, tmp_db: Path) -> None:
    """Carryover Task 15: alert detail must succeed even without a notification row
    (i.e. LEFT JOIN rather than INNER JOIN on notifications table).
    """
    _insert_customer(tmp_db, "c5", "000858.SZ", "五粮液", "消费")
    _insert_run(tmp_db, "run-5", "c5")
    _insert_alert(tmp_db, "alert-5", "run-5", "c5", "red")
    # Intentionally do NOT insert a notifications row
    resp = client.get("/api/monitoring/alerts/alert-5")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "alert-5"
    assert body["alert_level"] == "red"
    # notifications field should be an empty list (not 404, not crash)
    assert isinstance(body.get("notifications", []), list)


def test_get_alert_detail_with_notification(client: TestClient, tmp_db: Path) -> None:
    _insert_customer(tmp_db, "c6", "300750.SZ", "宁德时代", "新能源")
    _insert_run(tmp_db, "run-6", "c6")
    _insert_alert(tmp_db, "alert-6", "run-6", "c6", "red")
    with sqlite3.connect(tmp_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO notifications (id, alert_id, channel, send_status) VALUES (?, ?, ?, ?)",
            ("notif-6", "alert-6", "in_app", "sent"),
        )
    resp = client.get("/api/monitoring/alerts/alert-6")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "alert-6"
    notifs = body.get("notifications", [])
    assert len(notifs) >= 1
    assert notifs[0]["channel"] == "in_app"


# ---------------------------------------------------------------------------
# GET /api/monitoring/config
# ---------------------------------------------------------------------------


def test_get_config(client: TestClient) -> None:
    resp = client.get("/api/monitoring/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "scan_time" in data or "thresholds" in data
    # Both fields should be present per implementation
    assert "scan_time" in data
    assert "thresholds" in data
