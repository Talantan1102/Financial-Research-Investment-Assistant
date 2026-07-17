from enum import StrEnum


class RunStatus(StrEnum):
    QUEUED = "queued"
    ASSIGNED = "assigned"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_INPUT = "waiting_input"
    CANCEL_REQUESTED = "cancel_requested"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AttemptStatus(StrEnum):
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    LOST = "lost"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class TenantRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class PauseType(StrEnum):
    APPROVAL = "approval"
    INPUT = "input"


class WorkerStatus(StrEnum):
    ONLINE = "online"
    DRAINING = "draining"
    OFFLINE = "offline"


class OutboxType(StrEnum):
    ATTEMPT_ASSIGNED = "attempt.assigned"
    ATTEMPT_CANCEL = "attempt.cancel"
    SCHEDULE_WAKE = "schedule.wake"


ACTIVE_RUN_STATUSES = frozenset(
    {
        RunStatus.QUEUED,
        RunStatus.ASSIGNED,
        RunStatus.RUNNING,
        RunStatus.WAITING_APPROVAL,
        RunStatus.WAITING_INPUT,
        RunStatus.CANCEL_REQUESTED,
    }
)
TERMINAL_RUN_STATUSES = frozenset({RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED})

_ALLOWED_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.QUEUED: frozenset({RunStatus.ASSIGNED, RunStatus.CANCELLED}),
    RunStatus.ASSIGNED: frozenset(
        {RunStatus.RUNNING, RunStatus.QUEUED, RunStatus.CANCEL_REQUESTED}
    ),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.QUEUED,
            RunStatus.WAITING_APPROVAL,
            RunStatus.WAITING_INPUT,
            RunStatus.CANCEL_REQUESTED,
        }
    ),
    RunStatus.WAITING_APPROVAL: frozenset({RunStatus.QUEUED, RunStatus.CANCELLED}),
    RunStatus.WAITING_INPUT: frozenset({RunStatus.QUEUED, RunStatus.CANCELLED}),
    RunStatus.CANCEL_REQUESTED: frozenset({RunStatus.CANCELLED}),
}


class RunControlError(Exception):
    """Base class for run control domain errors."""


class InvalidRunTransition(RunControlError):  # noqa: N818 - domain contract fixes this name
    """Raised when a run status transition is not allowed."""


class ResourceNotFound(RunControlError):  # noqa: N818 - domain contract fixes this name
    """Raised when a requested run control resource does not exist."""


class SessionBusy(RunControlError):  # noqa: N818 - domain contract fixes this name
    """Raised when a session already has an active run."""


class TenantQueueFull(RunControlError):  # noqa: N818 - domain contract fixes this name
    """Raised when a tenant cannot queue another run."""


class IdempotencyConflict(RunControlError):  # noqa: N818 - domain contract fixes this name
    """Raised when an idempotency key is reused with different input."""


class ResumeNotAllowed(RunControlError):  # noqa: N818 - domain contract fixes this name
    """Raised when a paused run cannot be resumed."""


def assert_transition(current: RunStatus, target: RunStatus) -> None:
    if target not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise InvalidRunTransition(f"invalid run transition: {current.value} -> {target.value}")
