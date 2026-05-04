"""Integration test — full MonitoringService.run_scan with all-mock dependencies.

Exercises the complete data flow:
  1. DB seeded with monitoring_customers row
  2. MonitoringService constructed with mock detector/writer/escalator/notifier
  3. run_scan("c1") called
  4. Verify all 5 tables get written correctly

This is a white-box integration test (no real LLM / tushare / email calls).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.agents.portfolio_warning_schema import PortfolioWarningReport
from app.scripts.init_monitoring_tables import init_monitoring_tables
from app.services.monitoring.escalation import EscalationResult, EscalationStatus
from app.services.monitoring.monitoring_service import MonitoringService
from app.services.monitoring.notifications.email_notifier import EmailSendResult
from app.services.monitoring.signal_rules.base import (
    SignalLevel,
    SignalResult,
)

# ---------------------------------------------------------------------------
# Env setup (mock mode — no real network calls)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TUSHARE_MODE", "mock")
    monkeypatch.setenv("EMAIL_MODE", "mock")
    monkeypatch.setenv("LLM_MODE", "mock")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_customer(db_path: Path, cid: str = "c1") -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO monitoring_customers (id, ts_code, name, industry) VALUES (?, ?, ?, ?)",
            (cid, "600519.SH", "茅台", "消费"),
        )


def _build_report(level: SignalLevel, cid: str = "c1") -> PortfolioWarningReport:
    return PortfolioWarningReport(
        customer_id=cid,
        customer_name="茅台",
        ts_code="600519.SH",
        industry="消费",
        run_id="run-placeholder",
        alert_id="alert-placeholder",
        generated_at=datetime(2026, 5, 4),
        alert_level=level,
        summary="警告摘要",
        triggered_signals=[],
        recommendations=["建议1"],
    )


class _Mocks:
    escalator: Any
    notifier: Any


def _make_svc(
    db_path: Path,
    *,
    level: SignalLevel,
    report: PortfolioWarningReport,
    escalation: EscalationResult | None = None,
    email_success: bool = True,
) -> tuple[MonitoringService, _Mocks]:
    """Return (MonitoringService, mocks) — mocks for post-call assertions."""
    signals = [SignalResult(rule_name="cf", level=level, explanation="test")]

    detector = MagicMock()
    detector.detect = AsyncMock(return_value=(level, signals))

    writer = MagicMock()
    fake_state = MagicMock()
    fake_state.portfolio_warning_report = report
    writer.run = AsyncMock(return_value=fake_state)

    mocks = _Mocks()
    mocks.escalator = MagicMock()
    mocks.escalator.escalate = AsyncMock(
        return_value=escalation
        or EscalationResult(status=EscalationStatus.SUCCESS, deep_dive="deep analysis content")
    )

    mocks.notifier = MagicMock()
    mocks.notifier.send = AsyncMock(
        return_value=EmailSendResult(
            success=email_success,
            error=None if email_success else "SMTP refused",
        )
    )

    svc = MonitoringService(
        db_path=db_path,
        detector=detector,
        writer=writer,
        escalator=mocks.escalator,
        email_notifier=mocks.notifier,
        tushare=MagicMock(),
        bocha=MagicMock(),
        llm=MagicMock(),
        thresholds_per_rule={},
        recipient_emails=["test@example.com"],
    )
    return svc, mocks


# ---------------------------------------------------------------------------
# Smoke: MonitoringService importable + constructible
# ---------------------------------------------------------------------------


def test_monitoring_service_importable() -> None:
    """Basic smoke: class can be imported and the module is not broken."""
    from app.services.monitoring.monitoring_service import MonitoringService  # noqa: F401

    assert MonitoringService is not None


# ---------------------------------------------------------------------------
# Integration: green flow — only monitoring_runs + monitoring_signals written
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_green_flow(tmp_path: Path) -> None:
    db_path = tmp_path / "mon.sqlite"
    init_monitoring_tables(db_path)
    _seed_customer(db_path)

    svc, _ = _make_svc(
        db_path,
        level=SignalLevel.GREEN,
        report=_build_report(SignalLevel.GREEN),
    )
    run_ids = await svc.run_scan(["c1"], trigger_type="manual")

    assert len(run_ids) == 1
    with sqlite3.connect(db_path) as conn:
        runs = conn.execute("SELECT status FROM monitoring_runs").fetchall()
        signals = conn.execute("SELECT rule_name, level FROM monitoring_signals").fetchall()
        alerts = conn.execute("SELECT id FROM monitoring_alerts").fetchall()
        notifs = conn.execute("SELECT id FROM notifications").fetchall()

    assert runs == [("success",)]
    assert signals == [("cf", "green")]
    assert len(alerts) == 0
    assert len(notifs) == 0


# ---------------------------------------------------------------------------
# Integration: yellow flow — monitoring_alerts + in_app notification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_yellow_flow(tmp_path: Path) -> None:
    db_path = tmp_path / "mon.sqlite"
    init_monitoring_tables(db_path)
    _seed_customer(db_path)

    svc, mocks = _make_svc(
        db_path,
        level=SignalLevel.YELLOW,
        report=_build_report(SignalLevel.YELLOW),
    )
    await svc.run_scan(["c1"], trigger_type="cron")

    with sqlite3.connect(db_path) as conn:
        runs = conn.execute("SELECT status FROM monitoring_runs").fetchall()
        alerts = conn.execute("SELECT alert_level, escalated FROM monitoring_alerts").fetchall()
        notifs = conn.execute("SELECT channel FROM notifications").fetchall()

    assert runs == [("success",)]
    assert len(alerts) == 1
    assert alerts[0][0] == "yellow"
    assert alerts[0][1] == 0  # not escalated

    channels = [n[0] for n in notifs]
    assert "in_app" in channels
    assert "email" not in channels

    mocks.escalator.escalate.assert_not_called()
    mocks.notifier.send.assert_not_called()


# ---------------------------------------------------------------------------
# Integration: red flow — all 5 tables written
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_red_flow_all_tables_written(tmp_path: Path) -> None:
    """Red alert exercises all 5 monitoring tables."""
    db_path = tmp_path / "mon.sqlite"
    init_monitoring_tables(db_path)
    _seed_customer(db_path)

    svc, mocks = _make_svc(
        db_path,
        level=SignalLevel.RED,
        report=_build_report(SignalLevel.RED),
        escalation=EscalationResult(
            status=EscalationStatus.SUCCESS,
            deep_dive="detailed deep dive section",
        ),
    )
    await svc.run_scan(["c1"], trigger_type="disclosure_event")

    with sqlite3.connect(db_path) as conn:
        # Table 1: monitoring_runs
        runs = conn.execute("SELECT status, trigger_type FROM monitoring_runs").fetchall()
        # Table 2: monitoring_signals
        signals = conn.execute("SELECT level FROM monitoring_signals").fetchall()
        # Table 3: monitoring_alerts
        alerts = conn.execute(
            "SELECT alert_level, escalated, escalation_status, deep_dive_text "
            "FROM monitoring_alerts"
        ).fetchall()
        # Table 4 + 5: notifications (in_app + email rows)
        notifs = conn.execute(
            "SELECT channel, send_status FROM notifications ORDER BY channel"
        ).fetchall()

    # Table 1
    assert runs == [("success", "disclosure_event")]

    # Table 2
    assert len(signals) == 1
    assert signals[0][0] == "red"

    # Table 3
    assert len(alerts) == 1
    assert alerts[0][0] == "red"
    assert alerts[0][1] == 1  # escalated
    assert alerts[0][2] == "success"  # escalation_status
    assert alerts[0][3] == "detailed deep dive section"

    # Table 4+5 (notifications — in_app + email)
    channels = {n[0] for n in notifs}
    assert "in_app" in channels
    assert "email" in channels
    email_row = next(n for n in notifs if n[0] == "email")
    assert email_row[1] == "sent"

    mocks.escalator.escalate.assert_called_once()
    mocks.notifier.send.assert_called_once()


# ---------------------------------------------------------------------------
# Integration: concurrent customers (fan-out)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_concurrent_customers(tmp_path: Path) -> None:
    """Three customers scanned concurrently; all get run records."""
    db_path = tmp_path / "mon.sqlite"
    init_monitoring_tables(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        for i in range(3):
            conn.execute(
                "INSERT INTO monitoring_customers (id, ts_code, name, industry) "
                "VALUES (?, ?, ?, ?)",
                (f"c{i}", f"00000{i}.SH", f"公司{i}", "科技"),
            )

    svc, _ = _make_svc(
        db_path,
        level=SignalLevel.GREEN,
        report=_build_report(SignalLevel.GREEN),
    )
    run_ids = await svc.run_scan(["c0", "c1", "c2"], trigger_type="manual")

    assert len(run_ids) == 3
    with sqlite3.connect(db_path) as conn:
        runs = conn.execute(
            "SELECT customer_id, status FROM monitoring_runs ORDER BY customer_id"
        ).fetchall()

    assert len(runs) == 3
    for cid, status in runs:
        assert status == "success", f"customer {cid} had status {status}"


# ---------------------------------------------------------------------------
# Integration: MonitoringScheduler importable
# ---------------------------------------------------------------------------


def test_monitoring_scheduler_importable() -> None:
    from app.services.monitoring.scheduler import MonitoringScheduler  # noqa: F401

    assert MonitoringScheduler is not None
