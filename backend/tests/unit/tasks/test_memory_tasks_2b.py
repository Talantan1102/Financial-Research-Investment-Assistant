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


def test_extract_session_raises_not_implemented_in_skeleton() -> None:
    """In eager mode, autoretry_for=(Exception,) causes the task body's
    NotImplementedError to be wrapped in celery.exceptions.Retry; we just
    verify the original NotImplementedError lives in the chain.
    """
    from app.tasks.memory import extract_session_episodes_async
    from celery.exceptions import Retry

    with pytest.raises((Retry, NotImplementedError)) as exc_info:
        extract_session_episodes_async.apply(
            args=("00000000-0000-0000-0000-000000000000", "session_closed")
        ).get()
    # Original exception should be in the chain (Retry wraps it).
    msg = str(exc_info.value)
    assert (
        "Task 5" in msg
        or "NotImplementedError" in msg
        or isinstance(exc_info.value, NotImplementedError)
    )


def test_reconcile_raises_not_implemented_in_skeleton() -> None:
    from app.tasks.memory import reconcile_pending_milvus
    from celery.exceptions import Retry

    with pytest.raises((Retry, NotImplementedError)) as exc_info:
        reconcile_pending_milvus.apply().get()
    msg = str(exc_info.value)
    assert (
        "Task 6" in msg
        or "NotImplementedError" in msg
        or isinstance(exc_info.value, NotImplementedError)
    )


def test_extract_session_task_signature_max_retries_three() -> None:
    """Spec § 4 末尾矩阵 行 6 PG 主事务 max-3 retry — Celery task autoretry."""
    from app.tasks.memory import extract_session_episodes_async

    assert extract_session_episodes_async.max_retries == 3
    assert extract_session_episodes_async.acks_late is True
