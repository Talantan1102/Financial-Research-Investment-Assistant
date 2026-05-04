"""Unit tests for MonitoringScheduler — APScheduler integration.

Note: apscheduler is a legacy dependency that is not installed in the test
venv (only in production). Tests that require it are skipped unless available.
The _daily_scan / _disclosure_scan async methods are fully testable without
apscheduler since they only call MonitoringService.run_scan.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services.monitoring.scheduler import MonitoringScheduler

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scheduler(
    *,
    active_ids: list[str] | None = None,
    disclosure_ids: list[str] | None = None,
) -> tuple[MonitoringScheduler, MagicMock]:
    """Return (MonitoringScheduler, mock_monitoring_service)."""
    _active = active_ids if active_ids is not None else ["c1", "c2"]
    _disclosure = disclosure_ids if disclosure_ids is not None else ["c1"]

    svc = MagicMock()
    svc.run_scan = AsyncMock(return_value=["r1"])

    sched = MonitoringScheduler(
        monitoring_service=svc,
        load_active_customer_ids=lambda: _active,
        load_disclosure_customer_ids=lambda d: _disclosure,
    )
    return sched, svc


# ---------------------------------------------------------------------------
# install() — skipped if apscheduler unavailable
# ---------------------------------------------------------------------------


def test_install_adds_two_jobs() -> None:
    """install() calls add_job twice on the underlying APScheduler.

    Uses sys.modules patching so apscheduler and get_scheduler_service
    do not need to be really installed.
    """
    import sys
    from unittest.mock import patch

    mock_scheduler_instance = MagicMock()
    mock_svc_singleton = MagicMock()
    mock_svc_singleton._scheduler = mock_scheduler_instance

    mock_cron_trigger_cls = MagicMock(return_value=MagicMock())
    mock_cron_module = MagicMock()
    mock_cron_module.CronTrigger = mock_cron_trigger_cls

    mock_scheduler_service_module = MagicMock()
    mock_scheduler_service_module.get_scheduler_service = lambda: mock_svc_singleton

    with patch.dict(
        sys.modules,
        {
            "apscheduler": MagicMock(),
            "apscheduler.triggers": MagicMock(),
            "apscheduler.triggers.cron": mock_cron_module,
            "app.service.scheduler_service": mock_scheduler_service_module,
        },
    ):
        sched, _ = _make_scheduler()
        sched.install()

    assert mock_scheduler_instance.add_job.call_count == 2
    kwargs_ids = [c.kwargs.get("id") for c in mock_scheduler_instance.add_job.call_args_list]
    assert "monitoring_daily_scan" in kwargs_ids
    assert "monitoring_disclosure_check" in kwargs_ids


def test_install_idempotent() -> None:
    """Calling install() twice does not raise — replace_existing=True."""
    import sys
    from unittest.mock import patch

    mock_scheduler_instance = MagicMock()
    mock_svc_singleton = MagicMock()
    mock_svc_singleton._scheduler = mock_scheduler_instance

    mock_cron_module = MagicMock()
    mock_cron_module.CronTrigger = MagicMock(return_value=MagicMock())

    mock_scheduler_service_module = MagicMock()
    mock_scheduler_service_module.get_scheduler_service = lambda: mock_svc_singleton

    with patch.dict(
        sys.modules,
        {
            "apscheduler": MagicMock(),
            "apscheduler.triggers": MagicMock(),
            "apscheduler.triggers.cron": mock_cron_module,
            "app.service.scheduler_service": mock_scheduler_service_module,
        },
    ):
        sched, _ = _make_scheduler()
        sched.install()
        sched.install()

    assert mock_scheduler_instance.add_job.call_count == 4  # 2 jobs × 2 installs


# ---------------------------------------------------------------------------
# _daily_scan — delegates to run_scan(trigger_type="cron")
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_scan_calls_run_scan_cron() -> None:
    sched, svc = _make_scheduler(active_ids=["c1", "c2"])
    await sched._daily_scan()
    svc.run_scan.assert_awaited_once_with(["c1", "c2"], trigger_type="cron")


# ---------------------------------------------------------------------------
# _disclosure_scan — delegates to run_scan(trigger_type="disclosure_event")
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disclosure_scan_calls_run_scan_disclosure() -> None:
    sched, svc = _make_scheduler(disclosure_ids=["c1"])
    await sched._disclosure_scan()
    svc.run_scan.assert_awaited_once_with(["c1"], trigger_type="disclosure_event")


@pytest.mark.asyncio
async def test_disclosure_scan_passes_today_date() -> None:
    """load_disclosure_customer_ids receives today's date."""
    received_dates: list[date] = []

    svc = MagicMock()
    svc.run_scan = AsyncMock(return_value=[])

    sched = MonitoringScheduler(
        monitoring_service=svc,
        load_active_customer_ids=lambda: [],
        load_disclosure_customer_ids=lambda d: received_dates.append(d) or [],  # type: ignore[func-returns-value]
    )
    await sched._disclosure_scan()
    assert len(received_dates) == 1
    assert received_dates[0] == date.today()


# ---------------------------------------------------------------------------
# Empty customer list — no crash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_scan_empty_customers() -> None:
    svc = MagicMock()
    svc.run_scan = AsyncMock(return_value=[])

    sched = MonitoringScheduler(
        monitoring_service=svc,
        load_active_customer_ids=lambda: [],
        load_disclosure_customer_ids=lambda d: [],
    )
    await sched._daily_scan()
    svc.run_scan.assert_awaited_once_with([], trigger_type="cron")
