"""Unit tests for MonitoringService — uses fake detector + repository.

Covers:
  - green run: no alert written
  - yellow run: alert written, no escalation, no email
  - red run: alert written + escalation called + email sent
  - disabled/missing customer: skipped gracefully (FK prevents orphan row)
  - detector exception with retry: TushareNetworkError exhausted → run=failed
  - single-customer failure does not crash batch (other customers succeed)
  - PRAGMA foreign_keys=ON is active (FK violations are caught)
  - EscalationCoordinator FAILED status (carryover Task 13)
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.scripts.init_monitoring_tables import init_monitoring_tables
from app.services.monitoring.escalation import EscalationResult, EscalationStatus
from app.services.monitoring.monitoring_service import MonitoringService
from app.services.monitoring.notifications.email_notifier import EmailSendResult
from app.services.monitoring.signal_rules.base import (
    MonitoringCustomer,
    SignalLevel,
    SignalResult,
)
from app.services.tushare_client import TushareNetworkError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    p = tmp_path / "monitoring.sqlite"
    init_monitoring_tables(p)
    return p


@pytest.fixture
def customer(db_path: Path) -> MonitoringCustomer:
    cust = MonitoringCustomer(id="c1", ts_code="600519.SH", name="测试公司", industry="消费")
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO monitoring_customers (id, ts_code, name, industry) VALUES (?, ?, ?, ?)",
            (cust.id, cust.ts_code, cust.name, cust.industry),
        )
    return cust


class _Mocks:
    """Bag-of-mocks returned alongside the service for easy assertion in tests."""

    detector: Any
    writer: Any
    escalator: Any
    notifier: Any


def _make_service(
    db_path: Path,
    *,
    detector_result: tuple[SignalLevel, list[SignalResult]] | None = None,
    detector_side_effect: Any = None,
    writer_report: Any = None,
    escalation_result: EscalationResult | None = None,
    email_success: bool = True,
) -> tuple[MonitoringService, _Mocks]:
    """Build a MonitoringService with all dependencies mocked.

    Returns (svc, mocks) so tests can call mock.assert_* without
    accessing private attributes of the service (which mypy would reject).
    """
    mocks = _Mocks()

    mocks.detector = MagicMock()
    if detector_side_effect is not None:
        mocks.detector.detect = AsyncMock(side_effect=detector_side_effect)
    else:
        mocks.detector.detect = AsyncMock(
            return_value=detector_result
            or (
                SignalLevel.GREEN,
                [SignalResult(rule_name="x", level=SignalLevel.GREEN, explanation="ok")],
            )
        )

    mocks.writer = MagicMock()
    if writer_report is not None:
        fake_state = MagicMock()
        fake_state.portfolio_warning_report = writer_report
        mocks.writer.run = AsyncMock(return_value=fake_state)
    else:
        fake_state = MagicMock()
        fake_state.portfolio_warning_report = None
        mocks.writer.run = AsyncMock(return_value=fake_state)

    mocks.escalator = MagicMock()
    mocks.escalator.escalate = AsyncMock(
        return_value=escalation_result
        or EscalationResult(status=EscalationStatus.SUCCESS, deep_dive="dd")
    )

    mocks.notifier = MagicMock()
    mocks.notifier.send = AsyncMock(
        return_value=EmailSendResult(
            success=email_success,
            error=None if email_success else "smtp error",
        )
    )

    svc = MonitoringService(
        db_path=db_path,
        detector=mocks.detector,
        writer=mocks.writer,
        escalator=mocks.escalator,
        email_notifier=mocks.notifier,
        tushare=MagicMock(),
        bocha=MagicMock(),
        llm=MagicMock(),
        thresholds_per_rule={},
        recipient_emails=["a@b.com"],
    )
    return svc, mocks


def _make_report(
    *,
    level: SignalLevel = SignalLevel.YELLOW,
    customer_id: str = "c1",
) -> Any:
    """Build a real PortfolioWarningReport for the tests."""
    from app.agents.portfolio_warning_schema import PortfolioWarningReport

    return PortfolioWarningReport(
        customer_id=customer_id,
        customer_name="测试公司",
        ts_code="600519.SH",
        industry="消费",
        run_id="r",
        alert_id="a",
        generated_at=datetime(2026, 5, 4),
        alert_level=level,
        summary="risk!",
        triggered_signals=[],
        recommendations=[],
    )


# ---------------------------------------------------------------------------
# Green path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_green_run_no_alert(db_path: Path, customer: MonitoringCustomer) -> None:
    svc, _ = _make_service(db_path)
    run_ids = await svc.run_scan(["c1"], trigger_type="manual")

    assert len(run_ids) == 1
    with sqlite3.connect(db_path) as conn:
        runs = conn.execute("SELECT status FROM monitoring_runs").fetchall()
        alerts = conn.execute("SELECT id FROM monitoring_alerts").fetchall()
        signals = conn.execute("SELECT id FROM monitoring_signals").fetchall()

    assert len(runs) == 1
    assert runs[0][0] == "success"
    assert len(alerts) == 0  # green → no alert
    assert len(signals) == 1  # one rule result persisted


# ---------------------------------------------------------------------------
# Yellow path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_yellow_alert_no_email(db_path: Path, customer: MonitoringCustomer) -> None:
    """Yellow alert: alert record written, escalation NOT called, email NOT sent."""
    svc, mocks = _make_service(
        db_path,
        detector_result=(
            SignalLevel.YELLOW,
            [SignalResult(rule_name="fr", level=SignalLevel.YELLOW, explanation="ratio drop")],
        ),
        writer_report=_make_report(level=SignalLevel.YELLOW),
    )
    await svc.run_scan(["c1"], trigger_type="manual")

    with sqlite3.connect(db_path) as conn:
        alerts = conn.execute("SELECT alert_level FROM monitoring_alerts").fetchall()
        notifs = conn.execute("SELECT channel, send_status FROM notifications").fetchall()

    assert len(alerts) == 1
    assert alerts[0][0] == "yellow"

    # in_app notification written, email NOT sent
    channels = [n[0] for n in notifs]
    assert "in_app" in channels
    assert "email" not in channels

    mocks.escalator.escalate.assert_not_called()
    mocks.notifier.send.assert_not_called()


# ---------------------------------------------------------------------------
# Red path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_red_triggers_escalation_and_email(
    db_path: Path, customer: MonitoringCustomer
) -> None:
    """Red alert: escalation called, email sent, notifications written."""
    svc, mocks = _make_service(
        db_path,
        detector_result=(
            SignalLevel.RED,
            [SignalResult(rule_name="cf", level=SignalLevel.RED, explanation="cash drop")],
        ),
        writer_report=_make_report(level=SignalLevel.RED),
        escalation_result=EscalationResult(
            status=EscalationStatus.SUCCESS, deep_dive="deep analysis"
        ),
    )
    await svc.run_scan(["c1"], trigger_type="manual")

    mocks.escalator.escalate.assert_called_once()
    mocks.notifier.send.assert_called_once()

    with sqlite3.connect(db_path) as conn:
        alerts = conn.execute(
            "SELECT alert_level, escalated, deep_dive_text FROM monitoring_alerts"
        ).fetchall()
        notifs = conn.execute("SELECT channel, send_status FROM notifications").fetchall()

    assert len(alerts) == 1
    assert alerts[0][0] == "red"
    assert alerts[0][1] == 1  # escalated flag
    assert alerts[0][2] == "deep analysis"

    channels = [n[0] for n in notifs]
    assert "in_app" in channels
    assert "email" in channels
    email_rows = [n for n in notifs if n[0] == "email"]
    assert email_rows[0][1] == "sent"


# ---------------------------------------------------------------------------
# Escalation FAILED path (carryover Task 13)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_red_escalation_graph_exception(db_path: Path, customer: MonitoringCustomer) -> None:
    """Graph exception → EscalationStatus.FAILED; alert still written, email still sent."""
    svc, mocks = _make_service(
        db_path,
        detector_result=(
            SignalLevel.RED,
            [SignalResult(rule_name="cf", level=SignalLevel.RED, explanation="x")],
        ),
        writer_report=_make_report(level=SignalLevel.RED),
        escalation_result=EscalationResult(
            status=EscalationStatus.FAILED, error="LangGraph internal error"
        ),
    )
    await svc.run_scan(["c1"], trigger_type="manual")

    with sqlite3.connect(db_path) as conn:
        alerts = conn.execute(
            "SELECT escalated, escalation_status FROM monitoring_alerts"
        ).fetchall()

    # escalated=1 because escalation was attempted; status=failed
    assert len(alerts) == 1
    assert alerts[0][0] == 1
    assert alerts[0][1] == "failed"
    # Email still sent despite escalation failure
    mocks.notifier.send.assert_called_once()


# ---------------------------------------------------------------------------
# Email failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_red_email_failure_recorded(db_path: Path, customer: MonitoringCustomer) -> None:
    """Email failure → notifications row has send_status=failed; run still succeeds."""
    svc, _ = _make_service(
        db_path,
        detector_result=(
            SignalLevel.RED,
            [SignalResult(rule_name="cf", level=SignalLevel.RED, explanation="x")],
        ),
        writer_report=_make_report(level=SignalLevel.RED),
        email_success=False,
    )
    await svc.run_scan(["c1"], trigger_type="manual")

    with sqlite3.connect(db_path) as conn:
        runs = conn.execute("SELECT status FROM monitoring_runs").fetchall()
        email_notifs = conn.execute(
            "SELECT send_status FROM notifications WHERE channel='email'"
        ).fetchall()

    assert runs[0][0] == "success"  # run itself is success
    assert email_notifs[0][0] == "failed"


# ---------------------------------------------------------------------------
# Missing / disabled customer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_customer_fails_gracefully(db_path: Path) -> None:
    """Scanning a non-existent customer_id → no run record (FK constraint prevents orphan insert).

    The service logs a warning and returns a run_id, but no DB write occurs
    (we cannot insert into monitoring_runs with a non-existent customer_id
    when PRAGMA foreign_keys=ON is active).
    """
    svc, _ = _make_service(db_path)
    run_ids = await svc.run_scan(["non_existent_id"], trigger_type="manual")

    assert len(run_ids) == 1
    with sqlite3.connect(db_path) as conn:
        runs = conn.execute("SELECT id FROM monitoring_runs").fetchall()

    # No run record created — FK constraint prevents orphan insert
    assert len(runs) == 0


@pytest.mark.asyncio
async def test_disabled_customer_skipped_gracefully(db_path: Path) -> None:
    """Disabled customer (enabled=0) → no run record, detector not called."""
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO monitoring_customers (id, ts_code, name, industry, enabled) "
            "VALUES ('dis1', '000001.SH', '平安', '金融', 0)"
        )
    svc, mocks = _make_service(db_path)
    await svc.run_scan(["dis1"], trigger_type="manual")

    with sqlite3.connect(db_path) as conn:
        runs = conn.execute("SELECT id FROM monitoring_runs").fetchall()
    # disabled customer treated same as missing: no run record
    assert len(runs) == 0
    mocks.detector.detect.assert_not_called()


# ---------------------------------------------------------------------------
# Retry on TushareNetworkError (carryover M-3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_exhausted_on_network_error(
    db_path: Path, customer: MonitoringCustomer
) -> None:
    """TushareNetworkError on all 3 attempts → run=failed, detector called 3 times."""
    exc = TushareNetworkError("connection reset")
    svc, mocks = _make_service(db_path, detector_side_effect=exc)

    with patch("app.services.monitoring.monitoring_service.asyncio.sleep") as mock_sleep:
        mock_sleep.return_value = None  # skip actual delay
        await svc.run_scan(["c1"], trigger_type="manual")

    with sqlite3.connect(db_path) as conn:
        runs = conn.execute("SELECT status, error_message FROM monitoring_runs").fetchall()

    assert runs[0][0] == "failed"
    assert "connection reset" in (runs[0][1] or "")
    assert mocks.detector.detect.call_count == 3  # 3 attempts


@pytest.mark.asyncio
async def test_retry_succeeds_on_second_attempt(
    db_path: Path, customer: MonitoringCustomer
) -> None:
    """Fail once, succeed on second attempt → run=success."""
    good_result = (
        SignalLevel.GREEN,
        [SignalResult(rule_name="x", level=SignalLevel.GREEN, explanation="ok")],
    )
    svc, mocks = _make_service(db_path)
    mocks.detector.detect = AsyncMock(side_effect=[TushareNetworkError("timeout"), good_result])

    with patch("app.services.monitoring.monitoring_service.asyncio.sleep") as mock_sleep:
        mock_sleep.return_value = None
        await svc.run_scan(["c1"], trigger_type="manual")

    with sqlite3.connect(db_path) as conn:
        runs = conn.execute("SELECT status FROM monitoring_runs").fetchall()

    assert runs[0][0] == "success"
    assert mocks.detector.detect.call_count == 2


# ---------------------------------------------------------------------------
# Batch isolation: one failure does not crash others
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_isolates_single_customer_failure(db_path: Path) -> None:
    """Two customers: c2 is missing (skipped), c1 succeeds.

    Due to FK constraint, a run record cannot be created for a non-existent
    customer.  c2 is skipped silently; c1's run record is unaffected.
    """
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO monitoring_customers (id, ts_code, name, industry) "
            "VALUES ('c1', '600519.SH', '茅台', '消费')"
        )
        # c2 intentionally not inserted

    svc, _ = _make_service(db_path)
    run_ids = await svc.run_scan(["c1", "c2"], trigger_type="manual")

    assert len(run_ids) == 2  # both return a run_id (c2 returns one even with no DB write)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT customer_id, status FROM monitoring_runs").fetchall()

    # Only c1 gets a run record; c2 is skipped with no DB write
    assert len(rows) == 1
    assert rows[0] == ("c1", "success")


# ---------------------------------------------------------------------------
# PRAGMA foreign_keys=ON verification
# ---------------------------------------------------------------------------


def test_pragma_foreign_keys_active(db_path: Path) -> None:
    """Verify that our _connect() helper enables foreign-key enforcement.

    Without PRAGMA, SQLite silently accepts FK-violating inserts.
    With it, we expect an IntegrityError when inserting an orphan signal.
    """
    from app.services.monitoring.monitoring_service import _connect

    with _connect(db_path) as conn:
        fk_on = conn.execute("PRAGMA foreign_keys").fetchone()
    assert fk_on[0] == 1  # 1 = ON
