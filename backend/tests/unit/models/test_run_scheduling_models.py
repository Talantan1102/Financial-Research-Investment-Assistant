from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

import pytest
from app.core.database import Base
from app.models.run import Run, RunAttempt, RunMessage, RunSession
from app.models.run_scheduling import RunOutbox, RunTenantScheduling, RunWorker
from app.models.tenant import Tenant
from app.models.user import User
from app.run_control.types import OutboxType, WorkerStatus
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

WORKER_STATUSES = {"online", "draining", "offline"}
OUTBOX_TYPES = {"attempt.assigned", "attempt.cancel", "schedule.wake"}


@dataclass(frozen=True)
class OutboxProvenance:
    tenant: Tenant
    run: Run
    other_run: Run
    unclaimed_attempt: RunAttempt
    claimed_attempt: RunAttempt
    other_run_attempt: RunAttempt
    worker: RunWorker
    other_worker: RunWorker


@pytest.fixture
def outbox_provenance(db_session: Session) -> OutboxProvenance:
    suffix = uuid.uuid4().hex
    user = User(
        username=f"outbox-{suffix}",
        email=f"outbox-{suffix}@example.com",
        hashed_password="test-password-hash",
    )
    tenant = Tenant(name="Outbox tenant", slug=f"outbox-{suffix}")
    db_session.add_all([user, tenant])
    db_session.flush()
    run_session = RunSession(tenant_id=tenant.id, created_by_user_id=user.id)
    db_session.add(run_session)
    db_session.flush()
    messages = [
        RunMessage(
            tenant_id=tenant.id,
            session_id=run_session.id,
            role="user",
            content=f"prompt-{index}",
            status="complete",
        )
        for index in range(2)
    ]
    db_session.add_all(messages)
    db_session.flush()
    runs = [
        Run(
            tenant_id=tenant.id,
            session_id=run_session.id,
            created_by_user_id=user.id,
            run_type="chat",
            status="completed",
            idempotency_key=f"outbox-{index}-{suffix}",
            request_hash=uuid.uuid4().hex,
            input_message_id=messages[index].id,
            retry_count=0,
        )
        for index in range(2)
    ]
    workers = [
        RunWorker(worker_type="chat", capacity=1, status="online", metadata_payload={})
        for _ in range(2)
    ]
    db_session.add_all([*runs, *workers])
    db_session.flush()
    attempts = [
        RunAttempt(run_id=runs[0].id, attempt_no=1, status="assigned"),
        RunAttempt(
            run_id=runs[0].id,
            attempt_no=2,
            status="assigned",
            worker_id=workers[0].id,
        ),
        RunAttempt(run_id=runs[1].id, attempt_no=1, status="assigned"),
    ]
    db_session.add_all(attempts)
    db_session.flush()
    return OutboxProvenance(
        tenant=tenant,
        run=runs[0],
        other_run=runs[1],
        unclaimed_attempt=attempts[0],
        claimed_attempt=attempts[1],
        other_run_attempt=attempts[2],
        worker=workers[0],
        other_worker=workers[1],
    )


@pytest.fixture
def outbox_factory(
    outbox_provenance: OutboxProvenance,
) -> Callable[..., RunOutbox]:
    def factory(
        *,
        attempt_id: uuid.UUID | None,
        worker_id: uuid.UUID | None,
        run: Run | None = None,
        event_type: str = "attempt.cancel",
    ) -> RunOutbox:
        selected_run = run or outbox_provenance.run
        return RunOutbox(
            event_type=event_type,
            tenant_id=outbox_provenance.tenant.id,
            run_id=selected_run.id,
            attempt_id=attempt_id,
            worker_id=worker_id,
            payload={},
            dedupe_key=f"literal-{uuid.uuid4().hex}",
        )

    return factory


def _check_values(session: Session, table: str, constraint_name: str) -> set[str]:
    constraints = {
        constraint["name"]: constraint
        for constraint in inspect(session.get_bind()).get_check_constraints(table)
    }
    return set(re.findall(r"'([^']+)'", constraints[constraint_name]["sqltext"]))


def _foreign_keys(session: Session, table: str) -> dict[tuple[str, ...], Any]:
    return {
        tuple(constraint["constrained_columns"]): constraint
        for constraint in inspect(session.get_bind()).get_foreign_keys(table)
    }


def test_domain_types_have_exact_literal_contract() -> None:
    assert {status.value for status in WorkerStatus} == WORKER_STATUSES
    assert {event_type.value for event_type in OutboxType} == OUTBOX_TYPES


def test_fresh_metadata_create_all_includes_scheduling_tables(pg_test_engine: Engine) -> None:
    schema = f"run_scheduling_{uuid.uuid4().hex}"
    with pg_test_engine.connect() as connection, connection.begin():
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
        Base.metadata.create_all(bind=connection)
        table_names = set(inspect(connection).get_table_names())

    assert {"run_workers", "run_tenant_scheduling", "run_outbox"} <= table_names


def test_attempt_claim_and_worker_fields_have_exact_physical_contract(
    db_session: Session,
) -> None:
    columns = {
        column["name"]: column
        for column in inspect(db_session.get_bind()).get_columns("run_attempts")
    }
    assert columns["worker_id"]["type"].python_type is uuid.UUID
    for name in ("worker_id", "claim_token", "claimed_at", "last_heartbeat_at"):
        assert columns[name]["nullable"] is True
    assert columns["claim_token"]["type"].python_type is uuid.UUID


def test_attempt_active_worker_lease_index_matches_registry_predicate(
    db_session: Session,
) -> None:
    indexes = {
        index["name"]: index for index in inspect(db_session.get_bind()).get_indexes("run_attempts")
    }
    active_index = indexes["ix_run_attempts_active_worker_lease"]
    assert active_index["column_names"] == ["worker_id", "lease_expires_at"]
    predicate = re.sub(
        r"\s+",
        " ",
        str(active_index["dialect_options"]["postgresql_where"]),
    ).lower()
    assert "worker_id is not null" in predicate
    assert {"assigned", "running"} == set(re.findall(r"'([^']+)'", predicate))


def test_worker_checks_pin_chat_type_status_and_positive_capacity(db_session: Session) -> None:
    assert _check_values(db_session, "run_workers", "ck_run_workers_fixed_status") == (
        WORKER_STATUSES
    )
    checks = {
        constraint["name"]: constraint["sqltext"]
        for constraint in inspect(db_session.get_bind()).get_check_constraints("run_workers")
    }
    assert re.sub(r"\s+", " ", checks["ck_run_workers_chat_type"]).strip() == (
        "worker_type::text = 'chat'::text"
    )
    assert re.sub(r"\s+", " ", checks["ck_run_workers_positive_capacity"]).strip() == (
        "capacity > 0"
    )


def test_worker_rejects_non_positive_capacity(db_session: Session) -> None:
    db_session.add(
        RunWorker(
            worker_type="chat",
            capacity=0,
            status="online",
            metadata_payload={},
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_tenant_scheduling_uses_tenant_primary_key_and_fk(db_session: Session) -> None:
    primary_key = inspect(db_session.get_bind()).get_pk_constraint("run_tenant_scheduling")
    assert primary_key["constrained_columns"] == ["tenant_id"]
    foreign_keys = _foreign_keys(db_session, "run_tenant_scheduling")
    tenant_fk = foreign_keys[("tenant_id",)]
    assert tenant_fk["referred_table"] == "tenants"
    assert tenant_fk["referred_columns"] == ["id"]


def test_outbox_has_exact_type_check_unique_dedupe_and_retry_index(db_session: Session) -> None:
    assert _check_values(db_session, "run_outbox", "ck_run_outbox_fixed_type") == OUTBOX_TYPES
    unique_names = {
        constraint["name"]
        for constraint in inspect(db_session.get_bind()).get_unique_constraints("run_outbox")
    }
    assert "uq_run_outbox_dedupe_key" in unique_names
    checks = {
        constraint["name"]: re.sub(r"\s+", " ", constraint["sqltext"]).strip()
        for constraint in inspect(db_session.get_bind()).get_check_constraints("run_outbox")
    }
    assert checks["ck_run_outbox_worker_requires_attempt"] == (
        "worker_id IS NULL OR attempt_id IS NOT NULL"
    )
    indexes = {
        index["name"]: index for index in inspect(db_session.get_bind()).get_indexes("run_outbox")
    }
    assert indexes["ix_run_outbox_next_attempt_at"]["column_names"] == ["next_attempt_at"]


def test_outbox_composite_fks_preserve_tenant_attempt_worker_provenance(
    db_session: Session,
) -> None:
    foreign_keys = _foreign_keys(db_session, "run_outbox")
    run_fk = foreign_keys[("tenant_id", "run_id")]
    assert run_fk["referred_table"] == "runs"
    assert run_fk["referred_columns"] == ["tenant_id", "id"]
    attempt_fk = foreign_keys[("run_id", "attempt_id")]
    assert attempt_fk["referred_table"] == "run_attempts"
    assert attempt_fk["referred_columns"] == ["run_id", "id"]
    attempt_worker_fk = foreign_keys[("run_id", "attempt_id", "worker_id")]
    assert attempt_worker_fk["referred_table"] == "run_attempts"
    assert attempt_worker_fk["referred_columns"] == ["run_id", "id", "worker_id"]


def test_scheduling_models_expose_all_contract_columns() -> None:
    assert set(RunWorker.__table__.columns.keys()) == {
        "id",
        "worker_type",
        "capacity",
        "status",
        "heartbeat_at",
        "started_at",
        "last_assigned_at",
        "metadata",
    }
    assert set(RunTenantScheduling.__table__.columns.keys()) == {
        "tenant_id",
        "last_dispatched_at",
        "updated_at",
    }
    assert set(RunOutbox.__table__.columns.keys()) == {
        "id",
        "event_type",
        "tenant_id",
        "run_id",
        "attempt_id",
        "worker_id",
        "payload",
        "dedupe_key",
        "available_at",
        "claimed_at",
        "claimed_by",
        "delivered_at",
        "acknowledged_at",
        "next_attempt_at",
        "delivery_attempts",
        "last_error",
        "created_at",
    }
    assert {"claim_token", "claimed_at", "last_heartbeat_at"} <= set(
        RunAttempt.__table__.columns.keys()
    )


def test_attempt_worker_identity_is_available_for_composite_fk() -> None:
    unique_column_sets = {
        tuple(constraint.columns.keys())
        for constraint in cast(Any, RunAttempt.__table__).constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("run_id", "id", "worker_id") in unique_column_sets


def test_schedule_wake_allows_both_attempt_and_worker_null(
    db_session: Session,
    outbox_factory: Callable[..., RunOutbox],
) -> None:
    db_session.add(outbox_factory(attempt_id=None, worker_id=None, event_type="schedule.wake"))
    db_session.flush()


def test_assigned_unclaimed_cancel_allows_attempt_with_null_worker(
    db_session: Session,
    outbox_provenance: OutboxProvenance,
    outbox_factory: Callable[..., RunOutbox],
) -> None:
    db_session.add(
        outbox_factory(
            attempt_id=outbox_provenance.unclaimed_attempt.id,
            worker_id=None,
        )
    )
    db_session.flush()


def test_outbox_rejects_nonexistent_attempt_when_worker_is_null(
    db_session: Session,
    outbox_factory: Callable[..., RunOutbox],
) -> None:
    db_session.add(outbox_factory(attempt_id=uuid.uuid4(), worker_id=None))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_outbox_rejects_attempt_from_another_run_when_worker_is_null(
    db_session: Session,
    outbox_provenance: OutboxProvenance,
    outbox_factory: Callable[..., RunOutbox],
) -> None:
    db_session.add(
        outbox_factory(
            attempt_id=outbox_provenance.other_run_attempt.id,
            worker_id=None,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_outbox_rejects_worker_without_attempt(
    db_session: Session,
    outbox_provenance: OutboxProvenance,
    outbox_factory: Callable[..., RunOutbox],
) -> None:
    db_session.add(outbox_factory(attempt_id=None, worker_id=outbox_provenance.worker.id))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_outbox_rejects_worker_that_does_not_match_attempt(
    db_session: Session,
    outbox_provenance: OutboxProvenance,
    outbox_factory: Callable[..., RunOutbox],
) -> None:
    db_session.add(
        outbox_factory(
            attempt_id=outbox_provenance.claimed_attempt.id,
            worker_id=outbox_provenance.other_worker.id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
