"""L0 — Plan 2B Celery memory tasks 入口 + 队列路由 + autoretry 断言."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def celery_eager_memory_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    """L0/L1 eager mode — sync execution + propagate exceptions."""
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    monkeypatch.setenv("CELERY_TASK_EAGER_PROPAGATES", "1")


def test_extract_session_episodes_task_registered() -> None:
    # Ensure module gets imported so task self-registration runs
    import app.tasks.memory  # noqa: F401
    from app.tasks.celery_app import celery_app

    assert "app.tasks.memory.extract_session_episodes_async" in celery_app.tasks


def test_reconcile_pending_milvus_task_registered() -> None:
    import app.tasks.memory  # noqa: F401
    from app.tasks.celery_app import celery_app

    assert "app.tasks.memory.reconcile_pending_milvus" in celery_app.tasks


def test_extract_session_routed_to_memory_llm_queue() -> None:
    from app.tasks.celery_app import celery_app

    routes = celery_app.conf.task_routes or {}
    target = routes.get("app.tasks.memory.extract_session_episodes_async", {})
    assert target.get("queue") == "memory_llm"


def test_reconcile_routed_to_memory_llm_queue() -> None:
    from app.tasks.celery_app import celery_app

    routes = celery_app.conf.task_routes or {}
    target = routes.get("app.tasks.memory.reconcile_pending_milvus", {})
    assert target.get("queue") == "memory_llm"


def test_memory_llm_queue_defined() -> None:
    from app.tasks.celery_app import celery_app

    queue_names = {q.name for q in celery_app.conf.task_queues or []}
    assert "memory_llm" in queue_names


def test_extract_session_task_signature_max_retries_three() -> None:
    """Spec § 4 末尾矩阵 行 6 PG 主事务 max-3 retry — Celery task autoretry."""
    from app.tasks.memory import extract_session_episodes_async

    assert extract_session_episodes_async.max_retries == 3
    assert extract_session_episodes_async.acks_late is True


def test_reconcile_task_signature_acks_late_max_retries_two() -> None:
    """Beat retry job — acks_late + max_retries=2 (per Plan 2B Task 1 + 6)."""
    from app.tasks.memory import reconcile_pending_milvus

    assert reconcile_pending_milvus.max_retries == 2
    assert reconcile_pending_milvus.acks_late is True


def test_extract_session_episodes_runs_path_b_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """eager mode — task 调用 PathBRunner.run_for_session 并把 trigger_reason 透传."""
    from unittest.mock import AsyncMock, MagicMock

    from app.memory.path_b_runner import PathBRunResult
    from app.tasks import memory as memory_tasks

    fake_runner = MagicMock()
    fake_runner.run_for_session = AsyncMock(
        return_value=PathBRunResult(
            session_id="sid",
            trigger_reason="session_closed",
            episodes_scanned=2,
            chunks=1,
            facts_extracted=1,
            edges_inserted=1,
            failures=0,
            skipped=0,
        )
    )
    monkeypatch.setattr(memory_tasks, "_build_path_b_runner", lambda: fake_runner)

    out = memory_tasks.extract_session_episodes_async.apply(
        args=("00000000-0000-0000-0000-000000000099", "session_closed")
    ).get()
    assert out["session_id"] == "sid"
    assert out["facts_extracted"] == 1
    fake_runner.run_for_session.assert_awaited_once()


def test_extract_session_three_trigger_reasons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """3 trigger reason 都正常 dispatch 到 runner."""
    from unittest.mock import AsyncMock, MagicMock

    from app.memory.path_b_runner import PathBRunResult
    from app.tasks import memory as memory_tasks

    for reason in ("session_closed", "idle_30min", "new_session_started"):
        fake_runner = MagicMock()
        fake_runner.run_for_session = AsyncMock(
            return_value=PathBRunResult(
                session_id="sid",
                trigger_reason=reason,
                episodes_scanned=0,
                chunks=0,
                facts_extracted=0,
                edges_inserted=0,
                failures=0,
                skipped=0,
            )
        )
        monkeypatch.setattr(memory_tasks, "_build_path_b_runner", lambda r=fake_runner: r)
        out = memory_tasks.extract_session_episodes_async.apply(
            args=("00000000-0000-0000-0000-000000000077", reason)
        ).get()
        assert out["trigger_reason"] == reason


def test_extract_session_invalid_trigger_reason_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown trigger_reason → ValueError (autoretry wraps it; we accept either)."""
    from app.tasks import memory as memory_tasks
    from celery.exceptions import Retry

    # No runner needed — task body should reject before invoking runner.
    with pytest.raises((Retry, ValueError)):
        memory_tasks.extract_session_episodes_async.apply(
            args=("00000000-0000-0000-0000-000000000077", "BOGUS_REASON")
        ).get()
