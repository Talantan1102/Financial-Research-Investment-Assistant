from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any, cast

import pytest
from app.models.run import Run, RunAttempt, RunEvent, RunMessage, RunPause, RunSession
from app.models.tenant import Tenant
from app.models.user import User
from app.run_control.types import ACTIVE_RUN_STATUSES, PauseType, RunStatus
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


@pytest.fixture
def run_context(db_session: Session) -> tuple[Tenant, User, RunSession, tuple[RunMessage, ...]]:
    user = User(
        username=f"run-user-{uuid.uuid4().hex}",
        email=f"run-{uuid.uuid4().hex}@example.com",
        hashed_password="test-password-hash",
    )
    tenant = Tenant(name="Run tenant", slug=f"run-{uuid.uuid4().hex}")
    db_session.add_all([user, tenant])
    db_session.flush()

    session = RunSession(tenant_id=tenant.id, created_by_user_id=user.id, title="Session")
    db_session.add(session)
    db_session.flush()

    messages = tuple(
        RunMessage(
            tenant_id=tenant.id,
            session_id=session.id,
            role="user",
            content=f"prompt-{index}",
            status="complete",
        )
        for index in range(8)
    )
    db_session.add_all(messages)
    db_session.flush()
    return tenant, user, session, messages


@pytest.fixture
def run_rows(
    run_context: tuple[Tenant, User, RunSession, tuple[RunMessage, ...]],
) -> Callable[..., tuple[Run, ...]]:
    tenant, user, session, messages = run_context

    def factory(*, statuses: tuple[str, ...]) -> tuple[Run, ...]:
        return tuple(
            Run(
                tenant_id=tenant.id,
                session_id=session.id,
                created_by_user_id=user.id,
                run_type="chat",
                status=status,
                idempotency_key=f"request-{index}",
                request_hash=f"hash-{index}",
                input_message_id=messages[index].id,
                retry_count=0,
            )
            for index, status in enumerate(statuses)
        )

    return factory


def test_request_hash_is_required(
    db_session: Session, run_rows: Callable[..., tuple[Run, ...]]
) -> None:
    run = run_rows(statuses=(RunStatus.QUEUED.value,))[0]
    cast(Any, run).request_hash = None
    db_session.add(run)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_only_one_nonterminal_run_per_session(
    db_session: Session, run_rows: Callable[..., tuple[Run, ...]]
) -> None:
    first, second = run_rows(statuses=(RunStatus.QUEUED.value, RunStatus.RUNNING.value))
    db_session.add(first)
    db_session.flush()
    db_session.add(second)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_terminal_history_does_not_block_new_run(
    db_session: Session, run_rows: Callable[..., tuple[Run, ...]]
) -> None:
    completed, queued = run_rows(statuses=(RunStatus.COMPLETED.value, RunStatus.QUEUED.value))
    db_session.add_all([completed, queued])
    db_session.flush()


def test_every_active_status_is_covered_by_session_uniqueness(
    db_session: Session, run_rows: Callable[..., tuple[Run, ...]]
) -> None:
    statuses = tuple(status.value for status in sorted(ACTIVE_RUN_STATUSES, key=str))
    runs = run_rows(statuses=statuses)
    db_session.add(runs[0])
    db_session.flush()
    db_session.add_all(runs[1:])
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_run_indexes_are_created_with_expected_columns_and_predicate(
    db_session: Session,
) -> None:
    indexes = {index["name"]: index for index in inspect(db_session.get_bind()).get_indexes("runs")}

    queue_index = indexes["ix_runs_tenant_status_queued_at"]
    assert queue_index["column_names"] == ["tenant_id", "status", "queued_at"]

    active_index = indexes["uq_run_one_nonterminal_per_session"]
    assert active_index["unique"] is True
    assert active_index["column_names"] == ["session_id"]
    predicate = str(active_index["dialect_options"]["postgresql_where"])
    assert all(f"'{status.value}'" in predicate for status in ACTIVE_RUN_STATUSES)


def test_idempotency_tuple_is_unique(
    db_session: Session, run_rows: Callable[..., tuple[Run, ...]]
) -> None:
    first, second = run_rows(statuses=(RunStatus.COMPLETED.value, RunStatus.FAILED.value))
    second.idempotency_key = first.idempotency_key
    db_session.add_all([first, second])
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_run_type_is_chat_only(
    db_session: Session, run_rows: Callable[..., tuple[Run, ...]]
) -> None:
    run = run_rows(statuses=(RunStatus.QUEUED.value,))[0]
    cast(Any, run).run_type = "research"
    db_session.add(run)
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("retry_count", [-1, 2])
def test_retry_count_is_zero_or_one(
    db_session: Session,
    run_rows: Callable[..., tuple[Run, ...]],
    retry_count: int,
) -> None:
    run = run_rows(statuses=(RunStatus.QUEUED.value,))[0]
    cast(Any, run).retry_count = retry_count
    db_session.add(run)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_run_status_rejects_values_outside_contract(
    db_session: Session, run_rows: Callable[..., tuple[Run, ...]]
) -> None:
    run = run_rows(statuses=("unknown",))[0]
    db_session.add(run)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_attempt_number_is_unique_per_run(
    db_session: Session, run_rows: Callable[..., tuple[Run, ...]]
) -> None:
    run = run_rows(statuses=(RunStatus.COMPLETED.value,))[0]
    db_session.add(run)
    db_session.flush()
    db_session.add_all(
        [
            RunAttempt(run_id=run.id, attempt_no=1, status=RunStatus.RUNNING.value),
            RunAttempt(run_id=run.id, attempt_no=1, status=RunStatus.FAILED.value),
        ]
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_attempt_status_rejects_values_outside_contract(
    db_session: Session, run_rows: Callable[..., tuple[Run, ...]]
) -> None:
    run = run_rows(statuses=(RunStatus.COMPLETED.value,))[0]
    db_session.add(run)
    db_session.flush()
    db_session.add(RunAttempt(run_id=run.id, attempt_no=1, status="unknown"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_pause_number_is_unique_per_run(
    db_session: Session, run_rows: Callable[..., tuple[Run, ...]]
) -> None:
    run = run_rows(statuses=(RunStatus.COMPLETED.value,))[0]
    db_session.add(run)
    db_session.flush()
    db_session.add_all(
        [
            RunPause(
                run_id=run.id,
                pause_no=1,
                pause_type=PauseType.APPROVAL.value,
                request_payload={},
                continuation_payload={},
            ),
            RunPause(
                run_id=run.id,
                pause_no=1,
                pause_type=PauseType.INPUT.value,
                request_payload={},
                continuation_payload={},
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_pause_type_rejects_values_outside_contract(
    db_session: Session, run_rows: Callable[..., tuple[Run, ...]]
) -> None:
    run = run_rows(statuses=(RunStatus.COMPLETED.value,))[0]
    db_session.add(run)
    db_session.flush()
    db_session.add(
        RunPause(
            run_id=run.id,
            pause_no=1,
            pause_type="unknown",
            request_payload={},
            continuation_payload={},
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_event_sequence_is_unique_per_run(
    db_session: Session,
    run_rows: Callable[..., tuple[Run, ...]],
    run_context: tuple[Tenant, User, RunSession, tuple[RunMessage, ...]],
) -> None:
    tenant, _, _, _ = run_context
    run = run_rows(statuses=(RunStatus.COMPLETED.value,))[0]
    db_session.add(run)
    db_session.flush()
    db_session.add_all(
        [
            RunEvent(
                tenant_id=tenant.id,
                run_id=run.id,
                seq=1,
                event_type="run.created",
                payload={},
            ),
            RunEvent(
                tenant_id=tenant.id,
                run_id=run.id,
                seq=1,
                event_type="run.completed",
                payload={},
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
