from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

import pytest
from app.models.run import Run, RunAttempt, RunEvent, RunMessage, RunPause, RunSession
from app.models.tenant import Tenant
from app.models.user import User
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

RUN_STATUSES = (
    "queued",
    "assigned",
    "running",
    "waiting_approval",
    "waiting_input",
    "cancel_requested",
    "completed",
    "failed",
    "cancelled",
)
ACTIVE_RUN_STATUSES = {
    "queued",
    "assigned",
    "running",
    "waiting_approval",
    "waiting_input",
    "cancel_requested",
}
TERMINAL_RUN_STATUSES = ("completed", "failed", "cancelled")
ATTEMPT_STATUSES = ("assigned", "running", "completed", "failed", "lost", "cancelled", "paused")
PAUSE_TYPES = ("approval", "input")


@dataclass(frozen=True)
class RunContext:
    tenant: Tenant
    user: User
    session: RunSession
    messages: tuple[RunMessage, ...]


@pytest.fixture
def context_factory(db_session: Session) -> Callable[..., RunContext]:
    def factory(*, tenant: Tenant | None = None, user: User | None = None) -> RunContext:
        if user is None:
            user = User(
                username=f"run-user-{uuid.uuid4().hex}",
                email=f"run-{uuid.uuid4().hex}@example.com",
                hashed_password="test-password-hash",
            )
            db_session.add(user)
        if tenant is None:
            tenant = Tenant(name="Run tenant", slug=f"run-{uuid.uuid4().hex}")
            db_session.add(tenant)
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
        return RunContext(tenant=tenant, user=user, session=session, messages=messages)

    return factory


@pytest.fixture
def run_context(context_factory: Callable[..., RunContext]) -> RunContext:
    return context_factory()


def make_run(
    context: RunContext,
    *,
    status: str = "completed",
    message_index: int = 0,
    final_message: RunMessage | None = None,
    replaces_run_id: object | None = None,
    actor: User | None = None,
) -> Run:
    return Run(
        tenant_id=context.tenant.id,
        session_id=context.session.id,
        created_by_user_id=(actor or context.user).id,
        run_type="chat",
        status=status,
        idempotency_key=f"request-{uuid.uuid4().hex}",
        request_hash=uuid.uuid4().hex,
        input_message_id=context.messages[message_index].id,
        final_message_id=final_message.id if final_message is not None else None,
        replaces_run_id=replaces_run_id,
        retry_count=0,
    )


def check_values(db_session: Session, table: str, constraint_name: str) -> set[str]:
    constraints = {
        constraint["name"]: constraint
        for constraint in inspect(db_session.get_bind()).get_check_constraints(table)
    }
    return set(re.findall(r"'([^']+)'", constraints[constraint_name]["sqltext"]))


def foreign_keys(db_session: Session, table: str) -> dict[tuple[str, ...], Any]:
    return {
        tuple(constraint["constrained_columns"]): constraint
        for constraint in inspect(db_session.get_bind()).get_foreign_keys(table)
    }


def test_request_hash_is_required(db_session: Session, run_context: RunContext) -> None:
    run = make_run(run_context, status="queued")
    cast(Any, run).request_hash = None
    db_session.add(run)
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("status", RUN_STATUSES)
def test_run_status_accepts_every_exact_value(
    db_session: Session, run_context: RunContext, status: str
) -> None:
    db_session.add(make_run(run_context, status=status))
    db_session.flush()


def test_run_status_rejects_values_outside_contract(
    db_session: Session, run_context: RunContext
) -> None:
    db_session.add(make_run(run_context, status="unknown"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_run_status_check_has_exact_literal_contract(db_session: Session) -> None:
    assert check_values(db_session, "runs", "ck_runs_fixed_status") == set(RUN_STATUSES)


def test_only_one_nonterminal_run_per_session(db_session: Session, run_context: RunContext) -> None:
    db_session.add(make_run(run_context, status="queued", message_index=0))
    db_session.flush()
    db_session.add(make_run(run_context, status="running", message_index=1))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_all_terminal_history_does_not_block_new_run(
    db_session: Session, run_context: RunContext
) -> None:
    statuses = (*TERMINAL_RUN_STATUSES, "queued")
    db_session.add_all(
        [
            make_run(run_context, status=status, message_index=index)
            for index, status in enumerate(statuses)
        ]
    )
    db_session.flush()


def test_run_indexes_have_exact_physical_contract(db_session: Session) -> None:
    indexes = {index["name"]: index for index in inspect(db_session.get_bind()).get_indexes("runs")}
    assert indexes["ix_runs_tenant_status_queued_at"]["column_names"] == [
        "tenant_id",
        "status",
        "queued_at",
    ]
    active_index = indexes["uq_run_one_nonterminal_per_session"]
    assert active_index["unique"] is True
    assert active_index["column_names"] == ["session_id"]
    predicate = str(active_index["dialect_options"]["postgresql_where"])
    assert set(re.findall(r"'([^']+)'", predicate)) == ACTIVE_RUN_STATUSES
    assert indexes["ix_runs_tenant_session_revision_seq"]["column_names"] == [
        "tenant_id", "session_id", "revision_seq"
    ]
    assert indexes["ix_runs_replaces_run_id"]["column_names"] == ["replaces_run_id"]
    db_session.execute(text("SET LOCAL enable_seqscan = off"))
    plan = "\n".join(
        db_session.execute(
            text(
                "EXPLAIN SELECT id FROM runs "
                "WHERE tenant_id = :tenant_id AND session_id = :session_id "
                "ORDER BY revision_seq DESC LIMIT 20"
            ),
            {"tenant_id": uuid.uuid4(), "session_id": uuid.uuid4()},
        ).scalars()
    )
    assert "ix_runs_tenant_session_revision_seq" in plan


def test_idempotency_tuple_is_unique(db_session: Session, run_context: RunContext) -> None:
    first = make_run(run_context, status="completed", message_index=0)
    second = make_run(run_context, status="failed", message_index=1)
    second.idempotency_key = first.idempotency_key
    db_session.add_all([first, second])
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_run_type_is_chat_only(db_session: Session, run_context: RunContext) -> None:
    run = make_run(run_context, status="queued")
    cast(Any, run).run_type = "research"
    db_session.add(run)
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("retry_count", [-1, 2])
def test_retry_count_is_zero_or_one(
    db_session: Session, run_context: RunContext, retry_count: int
) -> None:
    run = make_run(run_context, status="queued")
    cast(Any, run).retry_count = retry_count
    db_session.add(run)
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("status", ATTEMPT_STATUSES)
def test_attempt_status_accepts_every_exact_value(
    db_session: Session, run_context: RunContext, status: str
) -> None:
    run = make_run(run_context)
    db_session.add(run)
    db_session.flush()
    db_session.add(RunAttempt(run_id=run.id, attempt_no=1, status=status))
    db_session.flush()


def test_attempt_status_rejects_values_outside_contract(
    db_session: Session, run_context: RunContext
) -> None:
    run = make_run(run_context)
    db_session.add(run)
    db_session.flush()
    db_session.add(RunAttempt(run_id=run.id, attempt_no=1, status="unknown"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_attempt_status_check_has_exact_literal_contract(db_session: Session) -> None:
    assert check_values(db_session, "run_attempts", "ck_run_attempts_fixed_status") == set(
        ATTEMPT_STATUSES
    )


def test_attempt_number_is_unique_per_run(db_session: Session, run_context: RunContext) -> None:
    run = make_run(run_context)
    db_session.add(run)
    db_session.flush()
    db_session.add_all(
        [
            RunAttempt(run_id=run.id, attempt_no=1, status="running"),
            RunAttempt(run_id=run.id, attempt_no=1, status="failed"),
        ]
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("pause_type", PAUSE_TYPES)
def test_pause_type_accepts_every_exact_value(
    db_session: Session, run_context: RunContext, pause_type: str
) -> None:
    run = make_run(run_context)
    db_session.add(run)
    db_session.flush()
    db_session.add(
        RunPause(
            run_id=run.id,
            pause_no=1,
            pause_type=pause_type,
            request_payload={},
            continuation_payload={},
        )
    )
    db_session.flush()


def test_pause_type_rejects_values_outside_contract(
    db_session: Session, run_context: RunContext
) -> None:
    run = make_run(run_context)
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


def test_pause_type_check_has_exact_literal_contract(db_session: Session) -> None:
    assert check_values(db_session, "run_pauses", "ck_run_pauses_fixed_type") == set(PAUSE_TYPES)


def test_pause_number_is_unique_per_run(db_session: Session, run_context: RunContext) -> None:
    run = make_run(run_context)
    db_session.add(run)
    db_session.flush()
    db_session.add_all(
        [
            RunPause(
                run_id=run.id,
                pause_no=1,
                pause_type="approval",
                request_payload={},
                continuation_payload={},
            ),
            RunPause(
                run_id=run.id,
                pause_no=1,
                pause_type="input",
                request_payload={},
                continuation_payload={},
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_event_sequence_is_unique_per_run(db_session: Session, run_context: RunContext) -> None:
    run = make_run(run_context)
    db_session.add(run)
    db_session.flush()
    db_session.add_all(
        [
            RunEvent(
                tenant_id=run_context.tenant.id,
                run_id=run.id,
                seq=1,
                event_type="run.created",
                payload={},
            ),
            RunEvent(
                tenant_id=run_context.tenant.id,
                run_id=run.id,
                seq=1,
                event_type="run.completed",
                payload={},
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_provenance_foreign_keys_are_restrict(db_session: Session) -> None:
    run_fks = foreign_keys(db_session, "runs")
    assert (
        run_fks[("tenant_id", "session_id", "input_message_id")]["options"]["ondelete"]
        == "RESTRICT"
    )
    assert (
        run_fks[("tenant_id", "session_id", "final_message_id")]["options"]["ondelete"]
        == "RESTRICT"
    )
    assert (
        run_fks[("tenant_id", "session_id", "created_by_user_id", "replaces_run_id")]["options"][
            "ondelete"
        ]
        == "RESTRICT"
    )
    event_fks = foreign_keys(db_session, "run_events")
    assert event_fks[("run_id", "attempt_id")]["options"]["ondelete"] == "RESTRICT"


def test_run_rejects_tenant_session_mismatch(
    db_session: Session, context_factory: Callable[..., RunContext]
) -> None:
    first = context_factory()
    second = context_factory()
    run = make_run(first)
    cast(Any, run).tenant_id = second.tenant.id
    db_session.add(run)
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("message_field", ["input_message_id", "final_message_id"])
def test_run_rejects_message_from_another_session(
    db_session: Session,
    context_factory: Callable[..., RunContext],
    message_field: str,
) -> None:
    first = context_factory()
    second = context_factory(tenant=first.tenant, user=first.user)
    run = make_run(first)
    setattr(run, message_field, second.messages[0].id)
    db_session.add(run)
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("message_field", ["input_message_id", "final_message_id"])
def test_run_rejects_message_from_another_tenant(
    db_session: Session,
    context_factory: Callable[..., RunContext],
    message_field: str,
) -> None:
    first = context_factory()
    second = context_factory()
    run = make_run(first)
    setattr(run, message_field, second.messages[0].id)
    db_session.add(run)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_replacement_must_match_session(
    db_session: Session, context_factory: Callable[..., RunContext]
) -> None:
    first = context_factory()
    second = context_factory(tenant=first.tenant, user=first.user)
    replaced = make_run(second)
    db_session.add(replaced)
    db_session.flush()
    db_session.add(make_run(first, replaces_run_id=replaced.id))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_replacement_must_match_tenant(
    db_session: Session, context_factory: Callable[..., RunContext]
) -> None:
    first = context_factory()
    second = context_factory()
    replaced = make_run(second)
    db_session.add(replaced)
    db_session.flush()
    db_session.add(make_run(first, replaces_run_id=replaced.id))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_replacement_must_match_actor(
    db_session: Session,
    run_context: RunContext,
    context_factory: Callable[..., RunContext],
) -> None:
    other_actor = context_factory(tenant=run_context.tenant).user
    replaced = make_run(run_context, actor=other_actor)
    db_session.add(replaced)
    db_session.flush()
    db_session.add(make_run(run_context, replaces_run_id=replaced.id))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_event_tenant_must_match_run(
    db_session: Session, context_factory: Callable[..., RunContext]
) -> None:
    first = context_factory()
    second = context_factory()
    run = make_run(first)
    db_session.add(run)
    db_session.flush()
    db_session.add(
        RunEvent(
            tenant_id=second.tenant.id,
            run_id=run.id,
            seq=1,
            event_type="run.created",
            payload={},
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_event_attempt_must_belong_to_same_run(
    db_session: Session, run_context: RunContext
) -> None:
    first = make_run(run_context, message_index=0)
    second = make_run(run_context, message_index=1)
    db_session.add_all([first, second])
    db_session.flush()
    attempt = RunAttempt(run_id=first.id, attempt_no=1, status="completed")
    db_session.add(attempt)
    db_session.flush()
    db_session.add(
        RunEvent(
            tenant_id=run_context.tenant.id,
            run_id=second.id,
            attempt_id=attempt.id,
            seq=1,
            event_type="run.completed",
            payload={},
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_final_message_delete_is_restricted(db_session: Session, run_context: RunContext) -> None:
    final_message = run_context.messages[1]
    db_session.add(make_run(run_context, final_message=final_message))
    db_session.flush()
    db_session.delete(final_message)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_replaced_run_delete_is_restricted(db_session: Session, run_context: RunContext) -> None:
    replaced = make_run(run_context, message_index=0)
    db_session.add(replaced)
    db_session.flush()
    db_session.add(make_run(run_context, message_index=1, replaces_run_id=replaced.id))
    db_session.flush()
    db_session.delete(replaced)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_event_attempt_delete_is_restricted(db_session: Session, run_context: RunContext) -> None:
    run = make_run(run_context)
    db_session.add(run)
    db_session.flush()
    attempt = RunAttempt(run_id=run.id, attempt_no=1, status="completed")
    db_session.add(attempt)
    db_session.flush()
    db_session.add(
        RunEvent(
            tenant_id=run_context.tenant.id,
            run_id=run.id,
            attempt_id=attempt.id,
            seq=1,
            event_type="run.completed",
            payload={},
        )
    )
    db_session.flush()
    db_session.delete(attempt)
    with pytest.raises(IntegrityError):
        db_session.flush()
