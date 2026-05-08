"""GET /signals + GET /signals/{id}/detail — user-scoped."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.monitoring import MonitoringAlert, MonitoringRun
from app.models.user import User


def _make_alert(session: Session, user_id: str, ts_code: str, status: str = "pending") -> str:
    run = MonitoringRun(
        id=str(uuid4()),
        user_id=user_id,
        cycle_id=str(uuid4()),
        trigger_type="cron",
        started_at=datetime.utcnow(),
        status="success",
    )
    session.add(run)
    session.flush()
    alert = MonitoringAlert(
        id=str(uuid4()),
        run_id=run.id,
        user_id=user_id,
        ts_code=ts_code,
        alert_level="red",
        report_json={"summary": "x"},
        detail_status=status,
    )
    session.add(alert)
    session.commit()
    return alert.id


def test_get_signals_returns_alerts_for_authed_user(client, session, fake_auth):
    user_id = fake_auth["user_id"]
    _make_alert(session, user_id, "600519.SH", status="ready")
    _make_alert(session, user_id, "300750.SZ", status="pending")

    r = client.get("/api/monitoring/signals", headers=fake_auth["headers"])
    assert r.status_code == 200, r.text
    items = r.json()["signals"]
    assert len(items) == 2


def test_get_signals_does_not_leak_other_users(client, session, fake_auth):
    own_user = fake_auth["user_id"]
    uid = uuid4().hex[:8]
    other_user = User(
        id=str(uuid4()),
        username=f"o-{uid}",
        email=f"o-{uid}@test",
        hashed_password="x",
        is_active=True,
    )
    session.add(other_user)
    session.flush()

    _make_alert(session, own_user, "600519.SH")
    _make_alert(session, other_user.id, "300750.SZ")  # 别 user 的 alert

    r = client.get("/api/monitoring/signals", headers=fake_auth["headers"])
    assert r.status_code == 200, r.text
    items = r.json()["signals"]
    assert all(item["ts_code"] == "600519.SH" for item in items)


def test_get_signal_detail_ready_returns_markdown(client, session, fake_auth):
    aid = _make_alert(session, fake_auth["user_id"], "600519.SH", status="ready")
    # update markdown
    session.query(MonitoringAlert).filter_by(id=aid).update(
        {"report_markdown": "# 异动详情\n茅台 -6%"}
    )
    session.commit()

    r = client.get(f"/api/monitoring/signals/{aid}/detail", headers=fake_auth["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["detail_status"] == "ready"
    assert "# 异动详情" in body["report_markdown"]


def test_get_signal_detail_pending_returns_placeholder(client, session, fake_auth):
    aid = _make_alert(session, fake_auth["user_id"], "600519.SH", status="pending")
    r = client.get(f"/api/monitoring/signals/{aid}/detail", headers=fake_auth["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["detail_status"] == "pending"


def test_get_signal_detail_cross_user_404(client, session, fake_auth):
    uid = uuid4().hex[:8]
    other = User(
        id=str(uuid4()),
        username=f"o-{uid}",
        email=f"o-{uid}@test",
        hashed_password="x",
        is_active=True,
    )
    session.add(other)
    session.flush()
    aid = _make_alert(session, other.id, "600519.SH")
    r = client.get(f"/api/monitoring/signals/{aid}/detail", headers=fake_auth["headers"])
    assert r.status_code == 404
