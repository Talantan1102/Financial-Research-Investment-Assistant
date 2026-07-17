from __future__ import annotations

import re
import uuid
from typing import Any, cast

import pytest
from app.core.database import Base
from app.models.run import RunAttempt
from app.models.run_scheduling import RunOutbox, RunTenantScheduling, RunWorker
from app.run_control.types import OutboxType, WorkerStatus
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

WORKER_STATUSES = {"online", "draining", "offline"}
OUTBOX_TYPES = {"attempt.assigned", "attempt.cancel", "schedule.wake"}


def _check_values(session: Session, table: str, constraint_name: str) -> set[str]:
    constraints = {
        constraint["name"]: constraint
        for constraint in inspect(session.get_bind()).get_check_constraints(table)
    }
    return set(re.findall(r"'([^']+)'", constraints[constraint_name]["sqltext"]))


def _foreign_keys(session: Session, table: str) -> dict[tuple[str, ...], dict[str, Any]]:
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
    attempt_fk = foreign_keys[("run_id", "attempt_id", "worker_id")]
    assert attempt_fk["referred_table"] == "run_attempts"
    assert attempt_fk["referred_columns"] == ["run_id", "id", "worker_id"]


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
