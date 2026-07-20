"""Privacy-safe traces and aggregate metrics for simulated order execution."""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from statistics import mean
from typing import cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
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
        "retry",
        "side",
        "status",
        "violation_count",
    }
)
_SAFE_TEXT = re.compile(r"^[a-z0-9_.:-]{1,64}$")
_TERMINAL = {
    OrderStatus.FILLED,
    OrderStatus.CANCELLED,
    OrderStatus.EXPIRED,
    OrderStatus.REJECTED,
}
_PROCESSING_SPANS = {"paper:match", "paper:settle"}


class LatencySummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    count: int = 0
    avg_ms: float = 0.0
    p95_ms: float = 0.0
    max_ms: float = 0.0


class PaperTradingAggregates(BaseModel):
    model_config = ConfigDict(frozen=True)

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
    safe_attrs: dict[str, object] = {"order_id": str(order_id)}
    for key, value in attrs.items():
        if key not in _SAFE_ATTRS or not isinstance(value, (bool, int, float, str)):
            continue
        if isinstance(value, str) and _SAFE_TEXT.fullmatch(value) is None:
            continue
        safe_attrs[key] = value
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
    try:
        writer(span)
    except Exception:
        logger.exception(
            "paper order trace writer failed",
            extra={"order_id": str(order_id), "span_name": span.name},
        )
    return span


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

    def aggregate(self) -> PaperTradingAggregates:
        with self._session_factory() as session:
            orders = list(session.scalars(select(PaperOrder)).all())
            spans = list(
                session.scalars(select(TraceSpanRow).where(TraceSpanRow.name.like("paper:%"))).all()
            )

        by_status = Counter(cast(OrderStatus, order.status).value for order in orders)
        reject_codes = Counter(
            cast(str, order.reject_code)
            for order in orders
            if order.status is OrderStatus.REJECTED and order.reject_code
        )
        first_processing: dict[str, datetime] = {}
        match_outcomes: Counter[str] = Counter()
        idempotency_intercepts = reconciliation_violations = reconciliation_errors = 0
        dispatch_failures = dispatch_recoveries = 0
        match_failures = match_conflicts = 0
        for span in spans:
            metadata = dict(span.attrs_json or {})
            order_id = metadata.get("order_id")
            if span.name in _PROCESSING_SPANS and isinstance(order_id, str):
                span_started_at = cast(datetime, span.started_at)
                current = first_processing.get(order_id)
                if current is None or span_started_at < current:
                    first_processing[order_id] = span_started_at
            if span.name == "paper:match":
                outcome = metadata.get("outcome")
                if isinstance(outcome, str):
                    match_outcomes[outcome] += 1
                match_failures += int(outcome == "failure")
                match_conflicts += int(metadata.get("error_code") == "match_pass_conflict")
            idempotency_intercepts += int(metadata.get("idempotent_replay") is True)
            reconciliation_violations += _nonnegative_int(metadata.get("violation_count"))
            reconciliation_errors += _nonnegative_int(metadata.get("reconciliation_errors"))
            dispatch_failures += int(metadata.get("dispatch_failed") is True)
            dispatch_recoveries += int(metadata.get("dispatch_recovered") is True)

        first_latencies: list[float] = []
        terminal_latencies: list[float] = []
        for order in orders:
            confirmed_at = cast(datetime | None, order.confirmed_at)
            if confirmed_at is None:
                continue
            first = first_processing.get(str(order.id))
            if first is not None and first >= confirmed_at:
                first_latencies.append((first - confirmed_at).total_seconds() * 1000)
            completed_at = cast(datetime | None, order.completed_at)
            if (
                order.status in _TERMINAL
                and completed_at is not None
                and completed_at >= confirmed_at
            ):
                terminal_latencies.append((completed_at - confirmed_at).total_seconds() * 1000)

        stuck_before = self._now() - self._stuck_after
        stuck_orders = sum(
            1
            for order in orders
            if order.status in {OrderStatus.QUEUED, OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED}
            and order.confirmed_at is not None
            and order.confirmed_at <= stuck_before
        )
        return PaperTradingAggregates(
            orders_by_status=dict(sorted(by_status.items())),
            stuck_orders=stuck_orders,
            confirmation_to_first_processing_ms=_latency_summary(first_latencies),
            confirmation_to_terminal_ms=_latency_summary(terminal_latencies),
            reject_codes=dict(sorted(reject_codes.items())),
            idempotency_intercepts=idempotency_intercepts,
            reconciliation_violations=reconciliation_violations,
            reconciliation_errors=reconciliation_errors,
            match_outcomes=dict(sorted(match_outcomes.items())),
            match_failures=match_failures,
            match_conflicts=match_conflicts,
            dispatch_failures=dispatch_failures,
            dispatch_recoveries=dispatch_recoveries,
        )


def _latency_summary(values: list[float]) -> LatencySummary:
    if not values:
        return LatencySummary()
    ordered = sorted(values)
    index = max(0, int((len(ordered) * 0.95) + 0.999999) - 1)
    return LatencySummary(
        count=len(ordered),
        avg_ms=round(mean(ordered), 3),
        p95_ms=round(ordered[index], 3),
        max_ms=round(ordered[-1], 3),
    )


def _nonnegative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(value, 0)
