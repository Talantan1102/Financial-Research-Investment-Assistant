"""MonitoringScheduler — wires cron jobs into the legacy APScheduler singleton.

Carryover from Task 13 spec § 4.3:
  - 16:30 Asia/Shanghai daily scan (trigger_type="cron")
  - 17:00 Asia/Shanghai disclosure-event scan (trigger_type="disclosure_event")

Uses the legacy get_scheduler_service() singleton from app/service/scheduler_service.py.
The singleton holds _scheduler (AsyncIOScheduler) and is already started by app_main.py;
MonitoringScheduler.install() just calls add_job() on the running instance.

Note: apscheduler is a legacy dependency declared in app/service/scheduler_service.py
but not yet in pyproject.toml. CronTrigger is imported lazily inside install() so
this module is importable without apscheduler in the venv (test environment).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from typing import Any

from app.services.monitoring.monitoring_service import MonitoringService

# get_scheduler_service imported lazily inside install() to avoid triggering
# app/service/__init__.py star-imports (which pull in llama_index / apscheduler
# that are not installed in the test venv).

_logger = logging.getLogger(__name__)


class MonitoringScheduler:
    """Adds monitoring cron jobs to the legacy APScheduler singleton.

    Args:
        monitoring_service: The MonitoringService instance to call.
        load_active_customer_ids: Callable[[], list[str]] — returns IDs of
            all enabled customers (queried from monitoring_customers table).
        load_disclosure_customer_ids: Callable[[date], list[str]] — returns
            IDs of customers with a disclosure event on the given date.
    """

    def __init__(
        self,
        monitoring_service: MonitoringService,
        load_active_customer_ids: Callable[[], list[str]],
        load_disclosure_customer_ids: Callable[[date], list[str]],
    ) -> None:
        self._service = monitoring_service
        self._load_active = load_active_customer_ids
        self._load_disclosure = load_disclosure_customer_ids

    def install(self) -> None:
        """Register the two monitoring cron jobs on the APScheduler singleton.

        Safe to call multiple times — replace_existing=True deduplicates by job ID.

        CronTrigger is imported lazily here so that this module is importable
        even when apscheduler is not installed (e.g., test environments that
        mock the scheduler singleton).
        """
        from apscheduler.triggers.cron import CronTrigger  # lazy — not in venv by default

        from app.service.scheduler_service import get_scheduler_service  # lazy — avoids llama_index

        scheduler_svc = get_scheduler_service()
        scheduler: Any = scheduler_svc._scheduler
        assert scheduler is not None, "APScheduler not yet initialised — call start() first"

        scheduler.add_job(
            self._daily_scan,
            CronTrigger(hour=16, minute=30, timezone="Asia/Shanghai"),
            id="monitoring_daily_scan",
            name="持仓预警日扫描",
            replace_existing=True,
        )
        scheduler.add_job(
            self._disclosure_scan,
            CronTrigger(hour=17, minute=0, timezone="Asia/Shanghai"),
            id="monitoring_disclosure_check",
            name="持仓预警披露日触发",
            replace_existing=True,
        )
        _logger.info(
            "monitoring scheduler installed: daily_scan @16:30, disclosure_check @17:00 (Asia/Shanghai)"
        )

    async def _daily_scan(self) -> None:
        cids = self._load_active()
        _logger.info("daily monitoring scan starting for %d customers", len(cids))
        await self._service.run_scan(cids, trigger_type="cron")

    async def _disclosure_scan(self) -> None:
        cids = self._load_disclosure(date.today())
        _logger.info("disclosure-event monitoring scan for %d customers", len(cids))
        await self._service.run_scan(cids, trigger_type="disclosure_event")
