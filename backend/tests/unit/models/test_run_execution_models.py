from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import pytest
from app.models.run import Run, RunAttempt, RunMessage, RunSession
from app.models.run_execution import RunToolExecution, RunUsageRecord
from app.models.tenant import Tenant
from app.models.user import User
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

TOOL_EXECUTION_STATUSES = {"started", "completed", "failed", "approval_required"}


@dataclass(frozen=True)
class ExecutionContext:
    runs: tuple[Run, Run]
    attempts: tuple[RunAttempt, RunAttempt]


@pytest.fixture
def execution_context(db_session: Session) -> ExecutionContext:
    suffix = uuid.uuid4().hex
    user = User(
        username=f"execution-{suffix}",
        email=f"execution-{suffix}@example.com",
        hashed_password="test-password-hash",
    )
    tenant = Tenant(name="Execution tenant", slug=f"execution-{suffix}")
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
    runs = tuple(
        Run(
            tenant_id=tenant.id,
            session_id=run_session.id,
            created_by_user_id=user.id,
            run_type="chat",
            status="completed",
            idempotency_key=f"execution-{index}-{suffix}",
            request_hash=uuid.uuid4().hex,
            input_message_id=messages[index].id,
            retry_count=0,
        )
        for index in range(2)
    )
    db_session.add_all(runs)
    db_session.flush()
    attempts = (
        RunAttempt(run_id=runs[0].id, attempt_no=1, status="completed"),
        RunAttempt(run_id=runs[1].id, attempt_no=1, status="completed"),
    )
    db_session.add_all(attempts)
    db_session.flush()
    return ExecutionContext(runs=runs, attempts=attempts)


def _checks(session: Session, table: str) -> dict[str, str]:
    return {
        constraint["name"]: re.sub(r"\s+", " ", constraint["sqltext"]).strip()
        for constraint in inspect(session.get_bind()).get_check_constraints(table)
    }


def _foreign_keys(session: Session, table: str) -> dict[tuple[str, ...], dict[str, object]]:
    return {
        tuple(constraint["constrained_columns"]): constraint
        for constraint in inspect(session.get_bind()).get_foreign_keys(table)
    }


def _tool_execution(context: ExecutionContext, **overrides: object) -> RunToolExecution:
    values: dict[str, object] = {
        "run_id": context.runs[0].id,
        "attempt_id": context.attempts[0].id,
        "tool_call_id": f"call-{uuid.uuid4().hex}",
        "idempotency_key": f"tool-{uuid.uuid4().hex}",
        "tool_name": "market.snapshot",
        "request_summary": {"ticker": "000001.SZ"},
        "status": "completed",
        "result_summary": {"price": 12.34},
    }
    values.update(overrides)
    return RunToolExecution(**values)


def _usage(context: ExecutionContext, **overrides: object) -> RunUsageRecord:
    values: dict[str, object] = {
        "run_id": context.runs[0].id,
        "attempt_id": context.attempts[0].id,
        "provider": "dashscope",
        "model": "qwen-plus",
        "input_tokens": 10,
        "output_tokens": 5,
        "cached_tokens": 3,
        "total_tokens": 15,
        "cost_cny": Decimal("0.00123456"),
    }
    values.update(overrides)
    return RunUsageRecord(**values)


def test_execution_tables_expose_exact_columns_and_session_archive() -> None:
    assert set(RunToolExecution.__table__.columns.keys()) == {
        "id",
        "run_id",
        "attempt_id",
        "tool_call_id",
        "idempotency_key",
        "tool_name",
        "request_summary",
        "status",
        "result_summary",
        "error_code",
        "error_message",
        "started_at",
        "finished_at",
    }
    assert set(RunUsageRecord.__table__.columns.keys()) == {
        "id",
        "run_id",
        "attempt_id",
        "provider",
        "model",
        "input_tokens",
        "output_tokens",
        "cached_tokens",
        "total_tokens",
        "cost_cny",
        "created_at",
    }
    assert "archived_at" in RunSession.__table__.columns


def test_tool_execution_physical_contract(db_session: Session) -> None:
    inspector = inspect(db_session.get_bind())
    uniques = {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("run_tool_executions")
    }
    assert uniques["uq_run_tool_idempotency"] == ("run_id", "idempotency_key")
    checks = _checks(db_session, "run_tool_executions")
    assert set(re.findall(r"'([^']+)'", checks["ck_run_tool_executions_fixed_status"])) == (
        TOOL_EXECUTION_STATUSES
    )
    assert (
        "octet_length(request_summary::text) <= 16384"
        in checks["ck_run_tool_request_summary_size"].lower()
    )
    assert (
        "octet_length(result_summary::text) <= 65536"
        in checks["ck_run_tool_result_summary_size"].lower()
    )


@pytest.mark.parametrize("status", sorted(TOOL_EXECUTION_STATUSES))
def test_tool_execution_accepts_exact_statuses(
    db_session: Session,
    execution_context: ExecutionContext,
    status: str,
) -> None:
    db_session.add(_tool_execution(execution_context, status=status))
    db_session.flush()


def test_tool_execution_rejects_unknown_status(
    db_session: Session, execution_context: ExecutionContext
) -> None:
    db_session.add(_tool_execution(execution_context, status="unknown"))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_summary", {"payload": "你" * 6000}),
        ("result_summary", {"payload": "你" * 23000}),
    ],
)
def test_tool_execution_rejects_oversized_json_summaries(
    db_session: Session,
    execution_context: ExecutionContext,
    field: str,
    value: object,
) -> None:
    db_session.add(_tool_execution(execution_context, **{field: value}))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_tool_execution_idempotency_is_global_per_run(
    db_session: Session, execution_context: ExecutionContext
) -> None:
    first = _tool_execution(execution_context, idempotency_key="stable-key")
    duplicate = _tool_execution(execution_context, idempotency_key="stable-key")
    db_session.add_all([first, duplicate])
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_tool_execution_idempotency_key_may_repeat_on_another_run(
    db_session: Session, execution_context: ExecutionContext
) -> None:
    db_session.add_all(
        [
            _tool_execution(execution_context, idempotency_key="stable-key"),
            _tool_execution(
                execution_context,
                run_id=execution_context.runs[1].id,
                attempt_id=execution_context.attempts[1].id,
                idempotency_key="stable-key",
            ),
        ]
    )
    db_session.flush()


@pytest.mark.parametrize("factory", [_tool_execution, _usage])
def test_execution_facts_reject_attempt_from_another_run(
    db_session: Session,
    execution_context: ExecutionContext,
    factory: object,
) -> None:
    record = factory(  # type: ignore[operator]
        execution_context,
        attempt_id=execution_context.attempts[1].id,
    )
    db_session.add(record)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_execution_facts_use_composite_attempt_provenance(db_session: Session) -> None:
    for table in ("run_tool_executions", "run_usage_records"):
        foreign_keys = _foreign_keys(db_session, table)
        run_fk = foreign_keys[("run_id",)]
        assert run_fk["referred_table"] == "runs"
        assert run_fk["referred_columns"] == ["id"]
        attempt_fk = foreign_keys[("run_id", "attempt_id")]
        assert attempt_fk["referred_table"] == "run_attempts"
        assert attempt_fk["referred_columns"] == ["run_id", "id"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"input_tokens": -1},
        {"output_tokens": -1},
        {"cached_tokens": -1},
        {"total_tokens": -1},
        {"cost_cny": Decimal("-0.00000001")},
    ],
)
def test_usage_rejects_negative_token_and_cost_values(
    db_session: Session,
    execution_context: ExecutionContext,
    overrides: dict[str, object],
) -> None:
    db_session.add(_usage(execution_context, **overrides))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_usage_accepts_zero_token_and_cost_values(
    db_session: Session, execution_context: ExecutionContext
) -> None:
    db_session.add(
        _usage(
            execution_context,
            input_tokens=0,
            output_tokens=0,
            cached_tokens=0,
            total_tokens=0,
            cost_cny=Decimal("0"),
        )
    )
    db_session.flush()


def test_usage_checks_and_model_token_query_index(db_session: Session) -> None:
    checks = _checks(db_session, "run_usage_records")
    for field in ("input_tokens", "output_tokens", "cached_tokens", "total_tokens", "cost_cny"):
        assert f"{field} >=" in checks[f"ck_run_usage_{field}_nonnegative"].lower()
    indexes = {
        index["name"]: index
        for index in inspect(db_session.get_bind()).get_indexes("run_usage_records")
    }
    assert indexes["ix_run_usage_model_total_tokens"]["column_names"] == [
        "model",
        "total_tokens",
    ]


def test_session_archive_is_nullable_indexed_and_utc_naive(
    db_session: Session, execution_context: ExecutionContext
) -> None:
    inspector = inspect(db_session.get_bind())
    columns = {column["name"]: column for column in inspector.get_columns("run_sessions")}
    assert columns["archived_at"]["nullable"] is True
    assert columns["archived_at"]["type"].timezone is False
    indexes = {index["name"]: index for index in inspector.get_indexes("run_sessions")}
    assert indexes["ix_run_sessions_archived_at"]["column_names"] == ["archived_at"]

    archived_at = datetime(2026, 7, 17, 3, 4, 5)
    session = db_session.query(RunSession).first()
    assert session is not None
    session.archived_at = archived_at
    db_session.flush()
    db_session.expire(session, ["archived_at"])
    assert session.archived_at == archived_at
    assert session.archived_at.tzinfo is None
