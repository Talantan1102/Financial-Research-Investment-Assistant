from __future__ import annotations

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
    dispatched: list[tuple[str, bool]] = []
    monkeypatch.setattr(tasks, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        tasks,
        "_open_queued_orders_in_session",
        MagicMock(return_value=(1, ["open-id", "partial-id"])),
    )
    monkeypatch.setattr(
        tasks,
        "dispatch_match_order",
        lambda order_id: dispatched.append((order_id, session.committed)) or True,
    )

    assert tasks.open_queued_orders.run() == 1
    assert dispatched == [("open-id", True), ("partial-id", True)]


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
