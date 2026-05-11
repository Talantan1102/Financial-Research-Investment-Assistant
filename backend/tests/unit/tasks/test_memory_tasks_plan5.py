"""L0(eager 模式)— Plan 5 memory Celery tasks (extract_episode_async /
extract_session_batch_async / posterior_calibration_weekly) 入口 + 队列路由 + body wiring.

契约 § 9 队列 = memory_llm. § 17 A1 task body 由本 plan ship.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def celery_eager(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    monkeypatch.setenv("CELERY_TASK_EAGER_PROPAGATES", "1")


# === 队列定义 + 路由 ===


def test_memory_llm_queue_registered() -> None:
    from app.tasks.celery_app import celery_app

    queues = {q.name for q in (celery_app.conf.task_queues or [])}
    assert "memory_llm" in queues


def test_extract_episode_async_routes_to_memory_llm() -> None:
    from app.tasks.celery_app import celery_app

    routes = celery_app.conf.task_routes or {}
    assert routes.get("app.tasks.memory.extract_episode_async") == {"queue": "memory_llm"}


def test_extract_session_batch_async_routes_to_memory_llm() -> None:
    from app.tasks.celery_app import celery_app

    routes = celery_app.conf.task_routes or {}
    assert routes.get("app.tasks.memory.extract_session_batch_async") == {"queue": "memory_llm"}


def test_posterior_calibration_weekly_routes_to_memory_llm() -> None:
    from app.tasks.celery_app import celery_app

    routes = celery_app.conf.task_routes or {}
    assert routes.get("app.tasks.memory.posterior_calibration_weekly") == {"queue": "memory_llm"}


# === Task 注册 ===


def test_extract_episode_async_registered() -> None:
    import app.tasks.memory  # noqa: F401
    from app.tasks.celery_app import celery_app

    assert "app.tasks.memory.extract_episode_async" in celery_app.tasks


def test_extract_session_batch_async_registered() -> None:
    import app.tasks.memory  # noqa: F401
    from app.tasks.celery_app import celery_app

    assert "app.tasks.memory.extract_session_batch_async" in celery_app.tasks


def test_posterior_calibration_weekly_registered() -> None:
    import app.tasks.memory  # noqa: F401
    from app.tasks.celery_app import celery_app

    assert "app.tasks.memory.posterior_calibration_weekly" in celery_app.tasks


# === Eager 调用 + body hook patch ===


def test_extract_episode_async_callable_via_eager() -> None:
    from app.tasks import memory as memory_tasks

    with patch.object(memory_tasks, "_run_extract_episode") as mock_run:
        mock_run.return_value = {"episode_id": "x", "facts_extracted": 3}
        result = memory_tasks.extract_episode_async.apply(args=["dummy-uuid"]).get()
        assert result["facts_extracted"] == 3
        mock_run.assert_called_once_with("dummy-uuid")


def test_extract_session_batch_async_callable_via_eager() -> None:
    from app.tasks import memory as memory_tasks

    with patch.object(memory_tasks, "_run_extract_session_batch") as mock_run:
        mock_run.return_value = {"session_id": "s1", "facts_extracted": 5}
        result = memory_tasks.extract_session_batch_async.apply(args=["s1"]).get()
        assert result["facts_extracted"] == 5
        mock_run.assert_called_once_with("s1")


def test_posterior_calibration_weekly_callable_via_eager() -> None:
    from app.tasks import memory as memory_tasks

    with patch.object(memory_tasks, "_run_posterior_calibration_weekly") as mock_run:
        mock_run.return_value = {"scanned_edges": 100, "promoted_to_high": 5}
        result = memory_tasks.posterior_calibration_weekly.apply().get()
        assert result["scanned_edges"] == 100


# === Beat schedule ===


def test_beat_schedule_contains_calibration_weekly() -> None:
    from app.tasks.celery_beat_schedule import beat_schedule

    assert "posterior_calibration_weekly" in beat_schedule
    entry = beat_schedule["posterior_calibration_weekly"]
    assert entry["task"] == "app.tasks.memory.posterior_calibration_weekly"
    # crontab object — schedule 不为 None
    assert entry["schedule"] is not None


def test_beat_schedule_still_has_milvus_reconcile() -> None:
    """Plan 2B beat schedule 行 5 不被本 plan 误删."""
    from app.tasks.celery_beat_schedule import beat_schedule

    assert "reconcile_pending_milvus" in beat_schedule
