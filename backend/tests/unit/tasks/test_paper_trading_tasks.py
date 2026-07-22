# mypy: disable-error-code="func-returns-value"

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest


def test_tasks_are_registered_with_stable_names_and_late_ack() -> None:
    from app.tasks.celery_app import celery_app
    from app.tasks.paper_trading import (
        expire_day_orders,
        match_order,
        open_queued_orders,
        release_t1_lots,
    )

    assert match_order.name == "app.tasks.paper_trading.match_order"
    assert match_order.acks_late is True
    assert open_queued_orders.name == "app.tasks.paper_trading.open_queued_orders"
    assert expire_day_orders.name == "app.tasks.paper_trading.expire_day_orders"
    assert release_t1_lots.name == "app.tasks.paper_trading.release_t1_lots"
    assert "app.tasks.paper_trading" in celery_app.conf.include


def test_paper_trading_beat_schedule_uses_shanghai_market_times() -> None:
    from app.tasks.celery_beat_schedule import beat_schedule

    assert str(beat_schedule["paper_open_queued_morning"]["schedule"]) == (
        "<crontab: 30 9 * * 1-5 (m/h/dM/MY/d)>"
    )
    assert str(beat_schedule["paper_open_queued_afternoon"]["schedule"]) == (
        "<crontab: 0 13 * * 1-5 (m/h/dM/MY/d)>"
    )
    assert str(beat_schedule["paper_expire_day_orders"]["schedule"]) == (
        "<crontab: 1 15 * * 1-5 (m/h/dM/MY/d)>"
    )
    assert str(beat_schedule["paper_release_t1_lots"]["schedule"]) == (
        "<crontab: 20 9 * * 1-5 (m/h/dM/MY/d)>"
    )


class _Session:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def test_match_order_commits_and_closes_session(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.tasks.paper_trading as tasks

    session = _Session()
    monkeypatch.setattr(tasks, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        tasks,
        "_match_order_in_session",
        MagicMock(return_value={"fill_ids": [], "matched_quantity": 0}),
    )

    result = tasks.match_order.run("00000000-0000-0000-0000-000000000001")

    assert result == {"fill_ids": [], "matched_quantity": 0}
    assert session.committed and session.closed
    assert not session.rolled_back


def test_match_order_rolls_back_closes_and_reraises(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.tasks.paper_trading as tasks

    session = _Session()
    monkeypatch.setattr(tasks, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        tasks, "_match_order_in_session", MagicMock(side_effect=RuntimeError("boom"))
    )

    with pytest.raises(RuntimeError, match="boom"):
        tasks.match_order.run(
            "00000000-0000-0000-0000-000000000001",
            datetime(2026, 7, 20, 1, 30, tzinfo=UTC).isoformat(),
            1,
        )

    assert session.rolled_back and session.closed
    assert not session.committed


@pytest.mark.parametrize(
    ("task_name", "runner_name", "result"),
    [
        ("expire_day_orders", "_expire_day_orders_in_session", 3),
        ("release_t1_lots", "_release_t1_lots_in_session", 4),
    ],
)
def test_maintenance_tasks_commit(
    monkeypatch: pytest.MonkeyPatch, task_name: str, runner_name: str, result: int
) -> None:
    import app.tasks.paper_trading as tasks

    session = _Session()
    monkeypatch.setattr(tasks, "SessionLocal", lambda: session)
    monkeypatch.setattr(tasks, runner_name, MagicMock(return_value=result))

    assert getattr(tasks, task_name).run() == result
    assert session.committed and session.closed
    assert not session.rolled_back


def test_open_queued_orders_dispatches_open_and_partial_orders_only_after_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.tasks.paper_trading as tasks

    session = _Session()
    dispatched: list[tuple[str, bool, bool]] = []
    monkeypatch.setattr(tasks, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        tasks,
        "_open_queued_orders_in_session",
        MagicMock(return_value=(1, ["open-id", "partial-id"])),
    )
    monkeypatch.setattr(
        tasks,
        "dispatch_match_order",
        lambda order_id, *, recovery=False: (
            dispatched.append((order_id, session.committed, recovery)) or True
        ),
    )

    assert tasks.open_queued_orders.run() == 1
    assert dispatched == [("open-id", True, True), ("partial-id", True, True)]


def test_periodic_scan_beat_recovers_open_and_partial_orders() -> None:
    from app.tasks.celery_beat_schedule import beat_schedule

    entry = beat_schedule["paper_scan_open_orders"]
    assert entry["task"] == "app.tasks.paper_trading.open_queued_orders"
    assert str(entry["schedule"]) == "<crontab: * 9-14 * * 1-5 (m/h/dM/MY/d)>"


def test_dispatch_failure_is_nonfatal_for_periodic_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.tasks.paper_trading as tasks

    monkeypatch.setattr(
        tasks.match_order, "apply_async", MagicMock(side_effect=OSError("redis down"))
    )

    assert tasks.dispatch_match_order("00000000-0000-0000-0000-000000000001") is False


def test_dispatch_propagates_trace_parent_and_records_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.tasks.paper_trading as tasks

    emitted: list[dict[str, object]] = []
    failure_states: list[dict[str, object]] = []
    monkeypatch.setattr(
        tasks.match_order, "apply_async", MagicMock(side_effect=OSError("redis down"))
    )
    monkeypatch.setattr(tasks, "_record_order_span", lambda **kwargs: emitted.append(kwargs))
    monkeypatch.setattr(
        tasks,
        "record_dispatch_failure_state",
        lambda **kwargs: failure_states.append(kwargs) or True,
    )

    assert (
        tasks.dispatch_match_order(
            "00000000-0000-0000-0000-000000000001",
            trace_parent_id="rest-confirm-span",
        )
        is False
    )
    tasks.match_order.apply_async.assert_called_once_with(
        args=["00000000-0000-0000-0000-000000000001"],
        kwargs={"trace_parent_id": emitted[0]["span_id"]},
        retry=False,
    )
    assert emitted[0]["name"] == "dispatch"
    assert emitted[0]["parent_id"] == "rest-confirm-span"
    assert emitted[0]["attrs"] == {"dispatch_failed": True, "outcome": "failure"}
    assert failure_states == [
        {
            "order_id": uuid.UUID("00000000-0000-0000-0000-000000000001"),
            "session_factory": tasks.SessionLocal,
        }
    ]


def test_periodic_dispatch_without_pending_failure_is_not_counted_as_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.tasks.paper_trading as tasks

    emitted: list[dict[str, object]] = []
    recovery_checks: list[dict[str, object]] = []
    monkeypatch.setattr(tasks.match_order, "apply_async", MagicMock())
    monkeypatch.setattr(tasks, "_record_order_span", lambda **kwargs: emitted.append(kwargs))
    monkeypatch.setattr(
        tasks,
        "record_dispatch_recovery_if_pending",
        lambda **kwargs: recovery_checks.append(kwargs) or False,
    )

    assert tasks.dispatch_match_order("00000000-0000-0000-0000-000000000001", recovery=True)

    assert len(recovery_checks) == 1
    assert emitted[0]["attrs"] == {"dispatch_failed": False, "outcome": "scan_dispatched"}
    assert "dispatch_recovered" not in emitted[0]["attrs"]


def test_match_records_idempotent_replay_without_counting_a_business_fill_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.tasks.paper_trading as tasks

    session = _Session()
    emitted: list[dict[str, object]] = []
    monkeypatch.setattr(tasks, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        tasks,
        "_match_order_in_session",
        MagicMock(
            return_value={
                "fill_ids": ["existing-fill"],
                "matched_quantity": 100,
                "idempotent_replay": True,
            }
        ),
    )
    monkeypatch.setattr(tasks, "_record_order_span", lambda **kwargs: emitted.append(kwargs))

    result = tasks.match_order.run(
        "00000000-0000-0000-0000-000000000001",
        trace_parent_id="rest-confirm-span",
    )

    assert "idempotent_replay" not in result
    assert emitted[0]["name"] == "match"
    assert emitted[0]["parent_id"] == "rest-confirm-span"
    assert emitted[0]["attrs"] == {
        "fill_count": 1,
        "idempotent_replay": True,
        "matched_quantity": 100,
        "outcome": "idempotent_replay",
    }
    assert len(emitted) == 1


def test_match_records_settlement_only_for_new_business_fills(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.tasks.paper_trading as tasks

    session = _Session()
    emitted: list[dict[str, object]] = []
    monkeypatch.setattr(tasks, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        tasks,
        "_match_order_in_session",
        MagicMock(return_value={"fill_ids": ["new-fill"], "matched_quantity": 100}),
    )
    monkeypatch.setattr(tasks, "_record_order_span", lambda **kwargs: emitted.append(kwargs))

    tasks.match_order.run("00000000-0000-0000-0000-000000000001")

    assert [row["name"] for row in emitted] == ["match", "settle"]
    assert emitted[1]["attrs"] == {
        "fill_count": 1,
        "matched_quantity": 100,
        "outcome": "success",
    }


def test_production_task_ignores_worker_fixture_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.tasks.paper_trading as tasks

    before = datetime.now(UTC) - timedelta(seconds=1)
    monkeypatch.setenv("PAPER_TRADING_WORKER_FIXTURE", "must-not-be-read.json")

    actual = tasks._now()

    assert before <= actual <= datetime.now(UTC) + timedelta(seconds=1)


def test_expiry_has_bounded_autoretry_and_periodic_recovery_beat() -> None:
    from app.tasks.celery_beat_schedule import beat_schedule
    from app.tasks.paper_trading import expire_day_orders

    assert expire_day_orders.max_retries == 3
    entry = beat_schedule["paper_expire_overdue_orders"]
    assert entry["task"] == "app.tasks.paper_trading.expire_day_orders"
    assert str(entry["schedule"]) == "<crontab: */10 * * * * (m/h/dM/MY/d)>"
