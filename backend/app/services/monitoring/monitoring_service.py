"""MonitoringService — 门面 for cron / event / manual scan trigger.

Per spec § 4.2 data flow:
  1. Load enabled customers from monitoring_customers
  2. Fan-out SignalDetector for each customer (concurrent, max=5)
  3. Persist monitoring_runs + monitoring_signals
  4. For yellow/red: persist monitoring_alerts + call Writer (alert_writer mode)
  5. For RED: call EscalationCoordinator → deep_dive_section
  6. Call EmailNotifier (fire-and-forget); persist notifications row
  7. Single-customer failure does NOT crash the batch

Carryover M-3 (Task 3): exponential backoff retry (max 3 attempts) on
TushareNetworkError and TushareError inside SignalDetector.detect().
Pattern mirrors reliable_bocha_service._do_with_retry.

Carryover I-3 (Task 6): PRAGMA foreign_keys = ON issued immediately after
every sqlite3.connect() call.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from app.agents.portfolio_warning_renderer import render_portfolio_warning_markdown
from app.agents.schemas import ResearchState
from app.services.monitoring.escalation import (
    EscalationCoordinator,
    EscalationResult,
    EscalationStatus,
)
from app.services.monitoring.signal_detector import SignalDetector
from app.services.monitoring.signal_rules.base import (
    MonitoringCustomer,
    SignalLevel,
    SignalResult,
)
from app.services.tushare_client import TushareError, TushareNetworkError

if TYPE_CHECKING:
    from app.agents.writer import Writer
    from app.services.bocha_factory import BochaService
    from app.services.llm_service import LLMService
    from app.services.monitoring.notifications.email_notifier import EmailNotifier
    from app.services.tushare_service import TushareService

_logger = logging.getLogger(__name__)

TriggerType = Literal["cron", "disclosure_event", "manual"]

_RETRY_MAX = 3
_RETRY_BASE_DELAY_S = 1.0


def _connect(db_path: Path) -> sqlite3.Connection:
    """Return a connection with foreign-key enforcement ON (carryover I-3)."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


class MonitoringService:
    """Unified entry point for the B-3 持仓预警 monitoring engine."""

    def __init__(
        self,
        *,
        db_path: Path,
        detector: SignalDetector,
        writer: Writer,
        escalator: EscalationCoordinator,
        email_notifier: EmailNotifier,
        tushare: TushareService,
        bocha: BochaService,
        llm: LLMService,
        thresholds_per_rule: dict[str, dict[str, float]],
        recipient_emails: list[str],
        max_concurrent_customers: int = 5,
    ) -> None:
        self._db_path = db_path
        self._detector = detector
        self._writer = writer
        self._escalator = escalator
        self._email_notifier = email_notifier
        self._tushare = tushare
        self._bocha = bocha
        self._llm = llm
        self._thresholds = thresholds_per_rule
        self._recipients = recipient_emails
        self._sem = asyncio.Semaphore(max_concurrent_customers)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run_scan(
        self,
        customer_ids: list[str],
        *,
        trigger_type: TriggerType = "manual",
    ) -> list[str]:
        """Scan a list of customers concurrently.  Returns run_ids in order."""

        async def _scan_one(cid: str) -> str:
            async with self._sem:
                return await self._scan_customer(cid, trigger_type)

        run_ids: list[str] = list(await asyncio.gather(*(_scan_one(c) for c in customer_ids)))
        return run_ids

    # ------------------------------------------------------------------
    # Per-customer scan with retry + persistence
    # ------------------------------------------------------------------

    async def _scan_customer(self, cid: str, trigger_type: TriggerType) -> str:
        run_id = str(uuid.uuid4())
        started_at = datetime.now()
        customer = self._load_customer(cid)
        if customer is None:
            # Cannot write a monitoring_runs row with FK enforcement when the
            # customer_id does not exist in monitoring_customers. Log and skip.
            _logger.warning("skipping scan for customer_id=%s: not found or disabled", cid)
            return run_id

        try:
            overall, results = await self._detect_with_retry(customer)
        except Exception as exc:
            _logger.error("scan failed for customer %s: %s", cid, exc)
            self._record_run(
                run_id,
                cid,
                trigger_type,
                started_at,
                datetime.now(),
                "failed",
                str(exc),
            )
            return run_id

        # Persist run (success) + signals
        self._record_run(
            run_id,
            cid,
            trigger_type,
            started_at,
            datetime.now(),
            "success",
            None,
        )
        for sig in results:
            self._record_signal(run_id, sig)

        if overall == SignalLevel.GREEN:
            return run_id

        # Yellow / Red → write alert + writer + maybe escalate + notify
        try:
            await self._handle_alert(run_id, cid, customer, overall, results)
        except Exception as exc:
            _logger.error("alert handling failed for customer %s: %s", cid, exc)
            # Alert handling failure does not fail the run record — signals already saved

        return run_id

    # ------------------------------------------------------------------
    # Retry wrapper (carryover M-3)
    # ------------------------------------------------------------------

    async def _detect_with_retry(
        self,
        customer: MonitoringCustomer,
    ) -> tuple[SignalLevel, list[SignalResult]]:
        """Run SignalDetector.detect with exponential backoff on transient errors.

        Max 3 attempts; delay sequence: 1s, 2s (jitter omitted — monitoring
        is not latency-sensitive enough to need it).
        Only retries TushareNetworkError / TushareError (transient network/API).
        """
        last_exc: Exception | None = None
        for attempt in range(_RETRY_MAX):
            try:
                return await self._detector.detect(
                    customer,
                    self._tushare,
                    self._bocha,
                    self._llm,
                    self._thresholds,
                )
            except (TushareNetworkError, TushareError) as exc:
                last_exc = exc
                if attempt < _RETRY_MAX - 1:
                    delay = _RETRY_BASE_DELAY_S * (2**attempt)
                    _logger.warning(
                        "detect attempt %d/%d failed (%s); retrying in %.1fs",
                        attempt + 1,
                        _RETRY_MAX,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
        # All retries exhausted
        if last_exc is None:
            raise RuntimeError("retry loop exited without exception (impossible)")
        raise last_exc

    # ------------------------------------------------------------------
    # Alert path
    # ------------------------------------------------------------------

    async def _handle_alert(
        self,
        run_id: str,
        cid: str,
        customer: MonitoringCustomer,
        overall: SignalLevel,
        results: list[SignalResult],
    ) -> None:
        alert_id = str(uuid.uuid4())

        # Call Writer in alert_writer mode to produce PortfolioWarningReport
        state = ResearchState(
            user_id="monitoring",
            session_id=cid,
            user_message=f"alert for {customer.name}",
            request_id=run_id,
            mode="alert_deep_dive",
            alert_signals=results,
        )
        new_state = await self._writer.run(state)
        report = new_state.portfolio_warning_report
        if report is None:
            _logger.warning("writer produced no report for customer %s", cid)
            return

        report = report.model_copy(update={"alert_id": alert_id, "alert_level": overall})

        # Escalation for RED alerts
        escalation: EscalationResult | None = None
        if overall == SignalLevel.RED:
            escalation = await self._escalator.escalate(customer, results, run_id)
            if escalation.status == EscalationStatus.SUCCESS and escalation.deep_dive:
                from app.agents.portfolio_warning_schema import DeepDiveSection

                report = report.model_copy(
                    update={"deep_dive": DeepDiveSection(content=escalation.deep_dive)}
                )

        markdown = render_portfolio_warning_markdown(report)
        self._record_alert(alert_id, run_id, cid, overall, report, markdown, escalation)

        await self._send_notifications(alert_id, overall, customer, report)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _load_customer(self, cid: str) -> MonitoringCustomer | None:
        with _connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT id, ts_code, name, industry, thresholds_override "
                "FROM monitoring_customers WHERE id = ? AND enabled = 1",
                (cid,),
            ).fetchone()
        if row is None:
            return None
        thresholds = json.loads(row[4]) if row[4] else None
        return MonitoringCustomer(
            id=row[0],
            ts_code=row[1],
            name=row[2],
            industry=row[3],
            thresholds_override=thresholds,
        )

    def _record_run(
        self,
        run_id: str,
        cid: str,
        trigger_type: str,
        started: datetime,
        finished: datetime,
        status: str,
        err: str | None,
    ) -> None:
        with _connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO monitoring_runs "
                "(id, customer_id, trigger_type, started_at, finished_at, status, error_message) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    cid,
                    trigger_type,
                    started.isoformat(),
                    finished.isoformat(),
                    status,
                    err,
                ),
            )

    def _record_signal(self, run_id: str, sig: SignalResult) -> None:
        with _connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO monitoring_signals "
                "(id, run_id, rule_name, level, detected_value, threshold, explanation, raw_data_ref) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    run_id,
                    sig.rule_name,
                    sig.level.value,
                    str(sig.detected_value) if sig.detected_value is not None else None,
                    str(sig.threshold) if sig.threshold is not None else None,
                    sig.explanation,
                    json.dumps(sig.raw_data_ref) if sig.raw_data_ref else None,
                ),
            )

    def _record_alert(
        self,
        alert_id: str,
        run_id: str,
        cid: str,
        level: SignalLevel,
        report: Any,
        markdown: str,
        escalation: EscalationResult | None,
    ) -> None:
        esc_status = escalation.status.value if escalation else None
        deep_dive = escalation.deep_dive if escalation else None
        with _connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO monitoring_alerts "
                "(id, run_id, customer_id, alert_level, report_json, report_markdown, "
                " escalated, escalation_status, deep_dive_text) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    alert_id,
                    run_id,
                    cid,
                    level.value,
                    report.model_dump_json(),
                    markdown,
                    1 if escalation else 0,
                    esc_status,
                    deep_dive,
                ),
            )

    async def _send_notifications(
        self,
        alert_id: str,
        level: SignalLevel,
        customer: MonitoringCustomer,
        report: Any,
    ) -> None:
        # In-app notification (always)
        with _connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO notifications (id, alert_id, channel, send_status) "
                "VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), alert_id, "in_app", "sent"),
            )

        # spec § 7.4 — email only for RED level
        if level != SignalLevel.RED:
            return

        subject = f"[B-3 持仓预警] {customer.name} - 红色等级 alert"
        body_text = f"客户: {customer.name}({customer.ts_code})\n等级: 红色\n\n{report.summary}"
        body_html = (
            f"<p>客户: <b>{customer.name}</b> ({customer.ts_code})</p><p>{report.summary}</p>"
        )
        result = await self._email_notifier.send(
            to_addrs=self._recipients,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )
        with _connect(self._db_path) as conn:
            for to in self._recipients:
                conn.execute(
                    "INSERT INTO notifications "
                    "(id, alert_id, channel, recipient, send_status, error_message) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        alert_id,
                        "email",
                        to,
                        "sent" if result.success else "failed",
                        result.error,
                    ),
                )
