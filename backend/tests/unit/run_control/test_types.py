from collections.abc import Iterator

import pytest
from app.run_control.types import (
    ACTIVE_RUN_STATUSES,
    TERMINAL_RUN_STATUSES,
    AttemptStatus,
    IdempotencyConflict,
    InvalidRunTransition,
    PauseType,
    ResourceNotFound,
    ResumeNotAllowed,
    RunControlError,
    RunStatus,
    SessionBusy,
    TenantQueueFull,
    TenantRole,
    assert_transition,
)


def test_attempt_status_values_match_persisted_contract() -> None:
    assert [status.value for status in AttemptStatus] == [
        "assigned",
        "running",
        "completed",
        "failed",
        "lost",
        "cancelled",
        "paused",
    ]


def test_run_status_values_match_persisted_contract() -> None:
    assert [status.value for status in RunStatus] == [
        "queued",
        "assigned",
        "running",
        "waiting_approval",
        "waiting_input",
        "cancel_requested",
        "completed",
        "failed",
        "cancelled",
    ]


def test_tenant_role_values_match_authorization_contract() -> None:
    assert [role.value for role in TenantRole] == ["owner", "admin", "member"]


def test_pause_type_values_match_pause_contract() -> None:
    assert [pause_type.value for pause_type in PauseType] == ["approval", "input"]


def test_waiting_is_nonterminal() -> None:
    assert RunStatus.WAITING_INPUT in ACTIVE_RUN_STATUSES
    assert RunStatus.COMPLETED not in ACTIVE_RUN_STATUSES


def test_active_and_terminal_statuses_partition_all_statuses() -> None:
    assert {
        RunStatus.QUEUED,
        RunStatus.ASSIGNED,
        RunStatus.RUNNING,
        RunStatus.WAITING_APPROVAL,
        RunStatus.WAITING_INPUT,
        RunStatus.CANCEL_REQUESTED,
    } == ACTIVE_RUN_STATUSES
    assert {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    } == TERMINAL_RUN_STATUSES
    assert ACTIVE_RUN_STATUSES.isdisjoint(TERMINAL_RUN_STATUSES)
    assert set(RunStatus) == ACTIVE_RUN_STATUSES | TERMINAL_RUN_STATUSES


_EXPECTED_TRANSITIONS = {
    RunStatus.QUEUED: {RunStatus.ASSIGNED, RunStatus.CANCELLED},
    RunStatus.ASSIGNED: {
        RunStatus.RUNNING,
        RunStatus.QUEUED,
        RunStatus.FAILED,
        RunStatus.CANCEL_REQUESTED,
    },
    RunStatus.RUNNING: {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.QUEUED,
        RunStatus.WAITING_APPROVAL,
        RunStatus.WAITING_INPUT,
        RunStatus.CANCEL_REQUESTED,
    },
    RunStatus.WAITING_APPROVAL: {RunStatus.QUEUED, RunStatus.CANCELLED},
    RunStatus.WAITING_INPUT: {RunStatus.QUEUED, RunStatus.CANCELLED},
    RunStatus.CANCEL_REQUESTED: {RunStatus.CANCELLED},
}


def _allowed_transitions() -> Iterator[object]:
    for current in RunStatus:
        for target in RunStatus:
            if target in _EXPECTED_TRANSITIONS.get(current, set()):
                yield pytest.param(current, target, id=f"{current.value}-to-{target.value}")


def _disallowed_transitions() -> Iterator[object]:
    for current in RunStatus:
        for target in RunStatus:
            if target not in _EXPECTED_TRANSITIONS.get(current, set()):
                yield pytest.param(current, target, id=f"{current.value}-to-{target.value}")


@pytest.mark.parametrize(("current", "target"), _allowed_transitions())
def test_allowed_transition_is_accepted(current: RunStatus, target: RunStatus) -> None:
    assert_transition(current, target)


@pytest.mark.parametrize(("current", "target"), _disallowed_transitions())
def test_unlisted_transition_is_rejected(current: RunStatus, target: RunStatus) -> None:
    with pytest.raises(InvalidRunTransition):
        assert_transition(current, target)


@pytest.mark.parametrize(
    "error_type",
    [
        InvalidRunTransition,
        ResourceNotFound,
        SessionBusy,
        TenantQueueFull,
        IdempotencyConflict,
        ResumeNotAllowed,
    ],
)
def test_domain_errors_share_run_control_base(error_type: type[RunControlError]) -> None:
    assert issubclass(error_type, RunControlError)
