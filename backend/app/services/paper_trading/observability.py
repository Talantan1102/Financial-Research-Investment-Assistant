"""Privacy-safe traces and aggregate metrics for simulated order execution."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.paper_order import OrderStatus, PaperOrder
from app.services.trace_models import Span, TraceSpanRow
from app.services.trace_service import TraceService

logger = logging.getLogger(__name__)

_SAFE_ATTRS = frozenset(
    {
        "dispatch_failed",
        "dispatch_recovered",
        "error_code",
        "fill_count",
        "idempotent_replay",
        "market_phase",
        "match_pass",
        "matched_quantity",
        "order_type",
        "outcome",
        "reconciliation_errors",
        "recovered_failure_count",
        "recovered_failure_span_ids",
        "retry",
        "side",
        "status",
        "violation_count",
    }
)
_SAFE_TEXT = re.compile(r"^[a-z0-9_.:-]{1,64}$")

_FIRST_PROCESSING_SQL = text(
    """
    WITH first_processing AS (
        SELECT metadata->>'order_id' AS order_id, min(started_at) AS first_at
        FROM trace_spans
        WHERE name IN ('paper:match', 'paper:settle')
          AND started_at >= :window_start AND started_at < :window_end
          AND metadata ? 'order_id'
        GROUP BY metadata->>'order_id'
    ), latencies AS (
        SELECT extract(epoch FROM (processing.first_at - orders.confirmed_at)) * 1000 AS ms
        FROM paper_orders AS orders
        JOIN first_processing AS processing ON processing.order_id = orders.id::text
        WHERE orders.confirmed_at IS NOT NULL
          AND processing.first_at >= orders.confirmed_at
    )
    SELECT count(*) AS count,
           COALESCE(avg(ms), 0) AS avg_ms,
           COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY ms), 0) AS p95_ms,
           COALESCE(max(ms), 0) AS max_ms
    FROM latencies
    """
)

_TERMINAL_LATENCY_SQL = text(
    """
    WITH latencies AS (
        SELECT extract(epoch FROM (completed_at - confirmed_at)) * 1000 AS ms
        FROM paper_orders
        WHERE status IN ('filled', 'cancelled', 'expired', 'rejected')
          AND confirmed_at IS NOT NULL AND completed_at >= confirmed_at
          AND completed_at >= :window_start AND completed_at < :window_end
    )
    SELECT count(*) AS count,
           COALESCE(avg(ms), 0) AS avg_ms,
           COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY ms), 0) AS p95_ms,
           COALESCE(max(ms), 0) AS max_ms
    FROM latencies
    """
)

_MATCH_OUTCOMES_SQL = text(
    """
    SELECT metadata->>'outcome' AS outcome, count(*) AS count
    FROM trace_spans
    WHERE name = 'paper:match'
      AND started_at >= :window_start AND started_at < :window_end
      AND metadata ? 'outcome'
    GROUP BY metadata->>'outcome'
    ORDER BY metadata->>'outcome'
    """
)

_SPAN_TOTALS_SQL = text(
    """
    SELECT
      count(*) FILTER (WHERE metadata->>'idempotent_replay' = 'true')
        AS idempotency_intercepts,
      COALESCE(sum(CASE WHEN metadata ? 'violation_count'
                        THEN (metadata->>'violation_count')::integer ELSE 0 END), 0)
        AS reconciliation_violations,
      COALESCE(sum(CASE WHEN metadata ? 'reconciliation_errors'
                        THEN (metadata->>'reconciliation_errors')::integer ELSE 0 END), 0)
        AS reconciliation_errors,
      count(*) FILTER (WHERE name = 'paper:match' AND metadata->>'outcome' = 'failure')
        AS match_failures,
      count(*) FILTER (WHERE name = 'paper:match'
                        AND metadata->>'error_code' = 'match_pass_conflict')
        AS match_conflicts,
      count(*) FILTER (WHERE name = 'paper:dispatch'
                        AND metadata->>'dispatch_failed' = 'true')
        AS dispatch_failures,
      count(*) FILTER (WHERE name = 'paper:dispatch'
                        AND metadata->>'dispatch_recovered' = 'true')
        AS dispatch_recoveries
    FROM trace_spans
    WHERE started_at >= :window_start AND started_at < :window_end
      AND name LIKE 'paper:%'
    """
)


class LatencySummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    count: int = 0
    avg_ms: float = 0.0
    p95_ms: float = 0.0
    max_ms: float = 0.0


class PaperTradingAggregates(BaseModel):
    model_config = ConfigDict(frozen=True)

    window_hours: int
    window_start: datetime
    window_end: datetime
    orders_by_status: dict[str, int] = Field(default_factory=dict)
    stuck_orders: int = 0
    confirmation_to_first_processing_ms: LatencySummary = Field(default_factory=LatencySummary)
    confirmation_to_terminal_ms: LatencySummary = Field(default_factory=LatencySummary)
    reject_codes: dict[str, int] = Field(default_factory=dict)
    idempotency_intercepts: int = 0
    reconciliation_violations: int = 0
    reconciliation_errors: int = 0
    match_outcomes: dict[str, int] = Field(default_factory=dict)
    match_failures: int = 0
    match_conflicts: int = 0
    dispatch_failures: int = 0
    dispatch_recoveries: int = 0


def paper_order_span(
    *,
    order_id: UUID,
    name: str,
    started_at: datetime,
    ended_at: datetime,
    attrs: dict[str, object],
    error: str | None = None,
) -> Span:
    """Build one correlated span while dropping PII and high-cardinality payloads."""
    safe_attrs = {"order_id": str(order_id), **_privacy_safe_attrs(attrs)}
    safe_error = error if error is not None and _SAFE_TEXT.fullmatch(error) else None
    return Span(
        span_id=f"paper-{order_id}-{name}-{uuid4().hex[:8]}",
        request_id=str(order_id),
        parent_id=None,
        name=f"paper:{name}",
        inputs={},
        outputs={},
        metadata=safe_attrs,
        started_at=started_at,
        ended_at=ended_at,
        error=safe_error,
    )


def paper_system_span(
    *,
    name: str,
    started_at: datetime,
    ended_at: datetime,
    attrs: dict[str, object],
    error: str | None = None,
) -> Span:
    """Build an aggregate-only span with no stable user/account/order identifier."""
    trace_id = f"paper-system-{uuid4()}"
    safe_error = error if error is not None and _SAFE_TEXT.fullmatch(error) else None
    return Span(
        span_id=f"{trace_id}-{name}-{uuid4().hex[:8]}",
        request_id=trace_id,
        parent_id=None,
        name=f"paper:{name}",
        inputs={},
        outputs={},
        metadata=_privacy_safe_attrs(attrs),
        started_at=started_at,
        ended_at=ended_at,
        error=safe_error,
    )


def write_paper_order_span(span: Span) -> None:
    """Best-effort persistence: observability must never break order processing."""
    try:
        TraceService(SessionLocal).write_span(span)
    except Exception:  # pragma: no cover - the contract is verified with an injected writer
        logger.exception(
            "paper order trace write failed",
            extra={"order_id": span.request_id, "span_name": span.name},
        )


def emit_paper_order_span(
    *,
    order_id: UUID,
    name: str,
    started_at: datetime,
    attrs: dict[str, object],
    error: str | None = None,
    parent_id: str | None = None,
    span_id: str | None = None,
    writer: Callable[[Span], None] = write_paper_order_span,
) -> Span:
    """Finish and persist a span without coupling telemetry to business success."""
    span = paper_order_span(
        order_id=order_id,
        name=name,
        started_at=started_at,
        ended_at=datetime.now(UTC),
        attrs=attrs,
        error=error,
    )
    if parent_id is not None:
        span = span.model_copy(update={"parent_id": parent_id})
    if span_id is not None:
        span = span.model_copy(update={"span_id": span_id})
    try:
        writer(span)
    except Exception:
        logger.exception(
            "paper order trace writer failed",
            extra={"order_id": str(order_id), "span_name": span.name},
        )
    return span


def emit_paper_system_span(
    *,
    name: str,
    started_at: datetime,
    attrs: dict[str, object],
    error: str | None = None,
    writer: Callable[[Span], None] = write_paper_order_span,
) -> Span:
    span = paper_system_span(
        name=name,
        started_at=started_at,
        ended_at=datetime.now(UTC),
        attrs=attrs,
        error=error,
    )
    try:
        writer(span)
    except Exception:
        logger.exception("paper system trace writer failed", extra={"span_name": span.name})
    return span


def record_dispatch_recovery_if_pending(
    *,
    order_id: UUID,
    started_at: datetime,
    parent_id: str | None,
    session_factory: Callable[[], AbstractContextManager[Session]] = SessionLocal,
) -> bool:
    """Atomically consume one persisted dispatch-failure incident after a successful scan."""
    try:
        with session_factory() as session:
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"paper-dispatch-recovery:{order_id}"},
            )
            pending_failure_span_ids = list(
                session.execute(
                    text(
                        """
                    SELECT failure.span_id
                    FROM trace_spans AS failure
                    WHERE failure.request_id = :request_id
                      AND failure.name = 'paper:dispatch'
                      AND failure.metadata->>'dispatch_failed' = 'true'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM trace_spans AS recovery
                          WHERE recovery.request_id = failure.request_id
                            AND recovery.name = 'paper:dispatch'
                            AND (
                                recovery.metadata->'recovered_failure_span_ids' ? failure.span_id
                                OR recovery.metadata->>'recovered_failure_span_id' = failure.span_id
                            )
                      )
                    ORDER BY failure.span_id
                    """
                    ),
                    {"request_id": str(order_id)},
                ).scalars()
            )
            if not pending_failure_span_ids:
                session.commit()
                return False
            span = paper_order_span(
                order_id=order_id,
                name="dispatch",
                started_at=started_at,
                ended_at=max(started_at, datetime.now(UTC)),
                attrs={
                    "dispatch_recovered": True,
                    "outcome": "recovered",
                    "recovered_failure_count": len(pending_failure_span_ids),
                    "recovered_failure_span_ids": [
                        str(span_id) for span_id in pending_failure_span_ids
                    ],
                },
            ).model_copy(update={"parent_id": parent_id})
            session.add(_trace_row(span))
            session.commit()
            return True
    except Exception:
        logger.exception(
            "paper dispatch recovery metric failed",
            extra={"order_id": str(order_id)},
        )
        return False


class PaperTradingAnalytics:
    def __init__(
        self,
        session_factory: Callable[[], AbstractContextManager[Session]],
        *,
        now: Callable[[], datetime] | None = None,
        stuck_after: timedelta = timedelta(minutes=5),
    ) -> None:
        self._session_factory = session_factory
        self._now = now or (lambda: datetime.now(UTC))
        self._stuck_after = stuck_after

    def aggregate(self, *, hours: int = 24) -> PaperTradingAggregates:
        if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= 168:
            raise ValueError("hours must be between 1 and 168")
        window_end = self._now()
        window_start = window_end - timedelta(hours=hours)
        params = {"window_start": window_start, "window_end": window_end}
        stuck_before = window_end - self._stuck_after

        with self._session_factory() as session:
            status_rows = session.execute(
                select(PaperOrder.status, func.count()).group_by(PaperOrder.status)
            ).all()
            stuck_orders = int(
                session.scalar(
                    select(func.count(PaperOrder.id)).where(
                        PaperOrder.status.in_(
                            [
                                OrderStatus.QUEUED,
                                OrderStatus.OPEN,
                                OrderStatus.PARTIALLY_FILLED,
                            ]
                        ),
                        PaperOrder.confirmed_at.is_not(None),
                        PaperOrder.confirmed_at <= stuck_before,
                    )
                )
                or 0
            )
            reject_rows = session.execute(
                select(PaperOrder.reject_code, func.count())
                .where(
                    PaperOrder.status == OrderStatus.REJECTED,
                    PaperOrder.reject_code.is_not(None),
                    PaperOrder.completed_at >= window_start,
                    PaperOrder.completed_at < window_end,
                )
                .group_by(PaperOrder.reject_code)
            ).all()
            first_latency = session.execute(_FIRST_PROCESSING_SQL, params).mappings().one()
            terminal_latency = session.execute(_TERMINAL_LATENCY_SQL, params).mappings().one()
            outcome_rows = session.execute(_MATCH_OUTCOMES_SQL, params).all()
            totals = session.execute(_SPAN_TOTALS_SQL, params).mappings().one()

        orders_by_status = {
            cast(OrderStatus, status).value: int(count) for status, count in status_rows
        }
        return PaperTradingAggregates(
            window_hours=hours,
            window_start=window_start,
            window_end=window_end,
            orders_by_status=dict(sorted(orders_by_status.items())),
            stuck_orders=stuck_orders,
            confirmation_to_first_processing_ms=_latency_from_row(first_latency),
            confirmation_to_terminal_ms=_latency_from_row(terminal_latency),
            reject_codes={str(code): int(count) for code, count in sorted(reject_rows)},
            idempotency_intercepts=int(totals["idempotency_intercepts"] or 0),
            reconciliation_violations=int(totals["reconciliation_violations"] or 0),
            reconciliation_errors=int(totals["reconciliation_errors"] or 0),
            match_outcomes={str(outcome): int(count) for outcome, count in outcome_rows},
            match_failures=int(totals["match_failures"] or 0),
            match_conflicts=int(totals["match_conflicts"] or 0),
            dispatch_failures=int(totals["dispatch_failures"] or 0),
            dispatch_recoveries=int(totals["dispatch_recoveries"] or 0),
        )


def _latency_from_row(row: object) -> LatencySummary:
    values = cast(dict[str, Any], row)
    return LatencySummary(
        count=int(values["count"] or 0),
        avg_ms=round(float(values["avg_ms"] or 0), 3),
        p95_ms=round(float(values["p95_ms"] or 0), 3),
        max_ms=round(float(values["max_ms"] or 0), 3),
    )


def _privacy_safe_attrs(attrs: dict[str, object]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, value in attrs.items():
        if key not in _SAFE_ATTRS:
            continue
        if key == "recovered_failure_span_ids" and isinstance(value, (list, tuple)):
            identifiers = [item for item in value if isinstance(item, str)]
            if len(identifiers) == len(value) and all(
                _SAFE_TEXT.fullmatch(item) is not None for item in identifiers
            ):
                safe[key] = identifiers
            continue
        if not isinstance(value, (bool, int, float, str)):
            continue
        if isinstance(value, str) and _SAFE_TEXT.fullmatch(value) is None:
            continue
        safe[key] = value
    return safe


def _trace_row(span: Span) -> TraceSpanRow:
    return TraceSpanRow(
        span_id=span.span_id,
        request_id=span.request_id,
        parent_id=span.parent_id,
        name=span.name,
        inputs=span.inputs,
        outputs=span.outputs,
        attrs_json=span.metadata,
        started_at=span.started_at,
        ended_at=span.ended_at,
        error=span.error,
    )
