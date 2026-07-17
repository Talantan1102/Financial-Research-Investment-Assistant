from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timedelta

from app.run_control.scheduling_policy import (
    EligibilityCandidate,
    EligibilityReason,
    RecoveryDecision,
    RunCandidate,
    TenantCandidate,
    WorkerCandidate,
    choose_run,
    choose_tenant,
    choose_worker,
    effective_queued_at,
    eligibility_reason,
    rank_workers,
    retry_decision,
)

NOW = datetime(2026, 7, 17, 9, 0, 0)


def test_eligibility_reports_every_rejection_reason_and_eligible() -> None:
    eligible = EligibilityCandidate(
        run_is_queued=True,
        cancel_requested=False,
        has_unresolved_pause=False,
        session_has_other_active_run=False,
        tenant_active_runs=1,
        tenant_max_running_runs=2,
        has_worker_capacity=True,
    )
    assert eligibility_reason(eligible) is EligibilityReason.ELIGIBLE

    cases = (
        (EligibilityReason.RUN_NOT_QUEUED, replace(eligible, run_is_queued=False)),
        (EligibilityReason.CANCEL_REQUESTED, replace(eligible, cancel_requested=True)),
        (EligibilityReason.UNRESOLVED_PAUSE, replace(eligible, has_unresolved_pause=True)),
        (
            EligibilityReason.SESSION_BUSY,
            replace(eligible, session_has_other_active_run=True),
        ),
        (EligibilityReason.TENANT_AT_CAPACITY, replace(eligible, tenant_active_runs=2)),
        (
            EligibilityReason.NO_WORKER_CAPACITY,
            replace(eligible, has_worker_capacity=False),
        ),
    )
    for expected, candidate in cases:
        assert eligibility_reason(candidate) is expected


def test_tenant_fairness_produces_a1_b1_c1_a2() -> None:
    tenant_ids = [uuid.UUID(int=value) for value in (1, 2, 3)]
    tenants = [TenantCandidate(id=tenant_id, last_dispatched_at=None) for tenant_id in tenant_ids]

    order: list[uuid.UUID] = []
    for offset in range(4):
        selected = choose_tenant(tenants)
        assert selected is not None
        order.append(selected.id)
        tenants = [
            TenantCandidate(
                id=item.id,
                last_dispatched_at=NOW + timedelta(seconds=offset)
                if item.id == selected.id
                else item.last_dispatched_at,
            )
            for item in tenants
        ]

    assert order == [tenant_ids[0], tenant_ids[1], tenant_ids[2], tenant_ids[0]]


def test_tenant_tie_break_is_stable_by_id() -> None:
    later_id = uuid.UUID(int=20)
    earlier_id = uuid.UUID(int=10)
    selected = choose_tenant(
        [
            TenantCandidate(id=later_id, last_dispatched_at=NOW),
            TenantCandidate(id=earlier_id, last_dispatched_at=NOW),
        ]
    )
    assert selected is not None
    assert selected.id == earlier_id


def test_fifo_and_finite_resume_boost() -> None:
    older_normal = RunCandidate(
        id=uuid.UUID(int=1),
        queued_at=NOW,
        queue_reason=None,
    )
    resumed = RunCandidate(
        id=uuid.UUID(int=2),
        queued_at=NOW + timedelta(seconds=20),
        queue_reason="resume",
    )
    too_new_resumed = RunCandidate(
        id=uuid.UUID(int=3),
        queued_at=NOW + timedelta(seconds=31),
        queue_reason="resume",
    )

    assert effective_queued_at(resumed, boost_seconds=30) == resumed.queued_at - timedelta(
        seconds=30
    )
    assert choose_run([older_normal, resumed], boost_seconds=30) == resumed
    assert choose_run([older_normal, too_new_resumed], boost_seconds=30) == older_normal


def test_run_fifo_tie_break_is_stable_by_id() -> None:
    first = RunCandidate(id=uuid.UUID(int=1), queued_at=NOW, queue_reason=None)
    second = RunCandidate(id=uuid.UUID(int=2), queued_at=NOW, queue_reason=None)
    assert choose_run([second, first], boost_seconds=30) == first


def test_worker_ranking_prefers_load_then_oldest_assignment_then_id() -> None:
    full_ratio = WorkerCandidate(
        id=uuid.UUID(int=1), capacity=2, active_attempts=1, last_assigned_at=None
    )
    empty_recent = WorkerCandidate(
        id=uuid.UUID(int=3), capacity=2, active_attempts=0, last_assigned_at=NOW
    )
    empty_never_later_id = WorkerCandidate(
        id=uuid.UUID(int=2), capacity=2, active_attempts=0, last_assigned_at=None
    )
    empty_never_earlier_id = WorkerCandidate(
        id=uuid.UUID(int=0), capacity=1, active_attempts=0, last_assigned_at=None
    )

    ranked = rank_workers([full_ratio, empty_recent, empty_never_later_id, empty_never_earlier_id])
    assert [item.id for item in ranked] == [
        empty_never_earlier_id.id,
        empty_never_later_id.id,
        empty_recent.id,
        full_ratio.id,
    ]
    assert choose_worker([full_ratio, empty_recent]) == empty_recent


def test_recovery_decision_cancels_retries_once_then_fails() -> None:
    assert retry_decision(cancel_requested=True, retry_count=0) is RecoveryDecision.CANCEL
    assert retry_decision(cancel_requested=False, retry_count=0) is RecoveryDecision.RETRY
    assert retry_decision(cancel_requested=False, retry_count=1) is RecoveryDecision.FAIL
