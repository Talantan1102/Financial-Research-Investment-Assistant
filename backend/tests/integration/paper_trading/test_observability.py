from __future__ import annotations

import uuid
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest
from app.models.paper_account import PaperAccount
from app.models.paper_order import OrderSide, OrderStatus, OrderType, PaperOrder
from app.models.user import User
from app.router.observability_router import router
from app.services.paper_trading.observability import emit_paper_order_span, paper_order_span
from app.services.trace_models import TraceSpanRow
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


@pytest.fixture
def user(db_session: Session) -> User:
    suffix = uuid.uuid4().hex[:12]
    row = User(
        username=f"paper-observability-{suffix}",
        email=f"paper-observability-{suffix}@example.test",
        hashed_password="not-used",
    )
    db_session.add(row)
    db_session.flush()
    return row


def _order(
    account: PaperAccount,
    user: User,
    *,
    status: OrderStatus,
    confirmed_at: datetime | None,
    completed_at: datetime | None = None,
    reject_code: str | None = None,
    filled_quantity: int = 0,
) -> PaperOrder:
    order_id = uuid.uuid4()
    return PaperOrder(
        id=order_id,
        account_id=account.id,
        account_generation=account.generation,
        user_id=user.id,
        client_request_id=(f"confirm-{order_id}" if confirmed_at else None),
        source_session_id="session",
        source_message_id=str(order_id),
        proposal_fingerprint=uuid.uuid4().hex * 2,
        ts_code="600519.SH",
        name="测试股票",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=100,
        limit_price=Decimal("10.00"),
        filled_quantity=filled_quantity,
        avg_fill_price=Decimal("10.00") if filled_quantity else None,
        reserved_cash=(
            Decimal("1000.00")
            if status in {OrderStatus.QUEUED, OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED}
            else Decimal("0.00")
        ),
        reserved_quantity=0,
        status=status,
        original_proposal={"quantity": 100},
        confirmed_payload={"quantity": 100} if confirmed_at else None,
        user_edits=None,
        quote_snapshot={"redacted": True},
        rules_version="test-rules",
        reject_code=reject_code,
        reject_message="rejected" if reject_code else None,
        expires_at=datetime.now(UTC) + timedelta(days=1),
        confirmed_at=confirmed_at,
        completed_at=completed_at,
    )


def _seed(db_session: Session, user: User) -> tuple[uuid.UUID, datetime]:
    now = datetime.now(UTC)
    account = PaperAccount.new(
        user_id=cast(uuid.UUID, user.id), generation=1, initial_cash=Decimal("100000.00")
    )
    db_session.add(account)
    db_session.flush()
    awaiting = _order(account, user, status=OrderStatus.AWAITING_CONFIRMATION, confirmed_at=None)
    queued = _order(
        account, user, status=OrderStatus.QUEUED, confirmed_at=now - timedelta(minutes=20)
    )
    partial = _order(
        account,
        user,
        status=OrderStatus.PARTIALLY_FILLED,
        confirmed_at=now - timedelta(seconds=10),
        filled_quantity=10,
    )
    rejected = _order(
        account,
        user,
        status=OrderStatus.REJECTED,
        confirmed_at=now - timedelta(seconds=4),
        completed_at=now - timedelta(seconds=1),
        reject_code="insufficient_cash",
    )
    db_session.add_all([awaiting, queued, partial, rejected])
    db_session.flush()
    db_session.add_all(
        [
            TraceSpanRow(
                span_id="match-partial",
                request_id=str(partial.id),
                parent_id="confirm-partial",
                name="paper:match",
                inputs={},
                outputs={},
                attrs_json={"order_id": str(partial.id), "outcome": "filled"},
                started_at=cast(datetime, partial.confirmed_at) + timedelta(seconds=2),
                ended_at=cast(datetime, partial.confirmed_at) + timedelta(seconds=3),
                error=None,
            ),
            TraceSpanRow(
                span_id="match-retry",
                request_id=str(partial.id),
                parent_id="confirm-partial",
                name="paper:match",
                inputs={},
                outputs={},
                attrs_json={
                    "order_id": str(partial.id),
                    "outcome": "idempotent_replay",
                    "idempotent_replay": True,
                },
                started_at=now,
                ended_at=now,
                error=None,
            ),
            TraceSpanRow(
                span_id="reconcile",
                request_id=str(partial.id),
                parent_id=None,
                name="paper:reconcile",
                inputs={},
                outputs={},
                attrs_json={"order_id": str(partial.id), "violation_count": 2},
                started_at=now,
                ended_at=now,
                error=None,
            ),
            TraceSpanRow(
                span_id="match-conflict",
                request_id=str(partial.id),
                parent_id=None,
                name="paper:match",
                inputs={},
                outputs={},
                attrs_json={
                    "order_id": str(partial.id),
                    "outcome": "failure",
                    "error_code": "match_pass_conflict",
                },
                started_at=now,
                ended_at=now,
                error="match_pass_conflict",
            ),
            TraceSpanRow(
                span_id="dispatch-failure",
                request_id=str(partial.id),
                parent_id=None,
                name="paper:dispatch",
                inputs={},
                outputs={},
                attrs_json={
                    "order_id": str(partial.id),
                    "dispatch_failed": True,
                    "outcome": "failure",
                },
                started_at=now,
                ended_at=now,
                error="dispatch_failed",
            ),
            TraceSpanRow(
                span_id="dispatch-recovery",
                request_id=str(partial.id),
                parent_id=None,
                name="paper:dispatch",
                inputs={},
                outputs={},
                attrs_json={
                    "order_id": str(partial.id),
                    "dispatch_recovered": True,
                    "outcome": "success",
                },
                started_at=now,
                ended_at=now,
                error=None,
            ),
        ]
    )
    db_session.flush()
    return cast(uuid.UUID, partial.id), now


def _client(db_session: Session) -> TestClient:
    import app.router.observability_router as module

    module._SESSION_FACTORY = lambda: nullcontext(db_session)  # type: ignore[assignment]
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_paper_order_span_has_stable_correlation_without_payload_data() -> None:
    order_id = uuid.uuid4()
    now = datetime.now(UTC)
    span = paper_order_span(
        order_id=order_id,
        name="confirm",
        started_at=now,
        ended_at=now + timedelta(milliseconds=25),
        attrs={
            "status": "open",
            "outcome": "success",
            "user_id": "must-not-leak",
            "quote": {"ts_code": "600519.SH", "price": "10.00"},
        },
    )
    assert span.request_id == str(order_id)
    assert span.name == "paper:confirm"
    assert span.metadata == {
        "order_id": str(order_id),
        "status": "open",
        "outcome": "success",
    }
    assert span.inputs == {} and span.outputs == {}


def test_emit_span_propagates_parent_and_trace_failure_never_escapes() -> None:
    order_id = uuid.uuid4()
    now = datetime.now(UTC)
    captured = []

    span = emit_paper_order_span(
        order_id=order_id,
        name="match",
        started_at=now,
        attrs={"outcome": "empty_book"},
        parent_id="rest-confirm-span",
        writer=captured.append,
    )
    assert span.parent_id == "rest-confirm-span"
    assert captured == [span]

    def broken_writer(_span) -> None:
        raise RuntimeError("trace database unavailable")

    emit_paper_order_span(
        order_id=order_id,
        name="settle",
        started_at=now,
        attrs={"outcome": "success"},
        writer=broken_writer,
    )


def test_paper_trading_aggregates_lifecycle_and_operational_metrics(
    db_session: Session, user: User
) -> None:
    _seed(db_session, user)
    response = _client(db_session).get("/api/v0/observability/paper-trading")
    assert response.status_code == 200
    body = response.json()
    assert body["orders_by_status"] == {
        "awaiting_confirmation": 1,
        "partially_filled": 1,
        "queued": 1,
        "rejected": 1,
    }
    assert body["stuck_orders"] == 1
    assert body["confirmation_to_first_processing_ms"]["count"] == 1
    assert body["confirmation_to_first_processing_ms"]["avg_ms"] == 2000.0
    assert body["confirmation_to_terminal_ms"]["count"] == 1
    assert body["confirmation_to_terminal_ms"]["avg_ms"] == 3000.0
    assert body["reject_codes"] == {"insufficient_cash": 1}
    assert body["idempotency_intercepts"] == 1
    assert body["reconciliation_violations"] == 2
    assert body["match_outcomes"] == {
        "failure": 1,
        "filled": 1,
        "idempotent_replay": 1,
    }
    assert body["match_failures"] == 1
    assert body["match_conflicts"] == 1
    assert body["dispatch_failures"] == 1
    assert body["dispatch_recoveries"] == 1


def test_paper_trading_endpoint_never_returns_pii_or_quote_payload(
    db_session: Session, user: User
) -> None:
    _seed(db_session, user)
    response = _client(db_session).get("/api/v0/observability/paper-trading")
    assert response.status_code == 200
    raw = response.text
    assert str(user.id) not in raw
    assert "600519.SH" not in raw
    assert "测试股票" not in raw
    assert "quote_snapshot" not in raw
