"""Celery app skeleton smoke tests."""

from __future__ import annotations

import importlib
import sys

import pytest


def test_celery_app_imports() -> None:
    """celery_app 应该可被导入,broker URL 从 env 读。"""
    from app.tasks.celery_app import celery_app

    assert celery_app.main == "monitoring"


def test_celery_app_broker_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """env CELERY_BROKER_URL 应该被 celery_app 模块加载时拾取。"""
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://test:6379/0")
    # Reload submodule via sys.modules — `app.tasks.__init__` re-exports the
    # Celery instance under name `celery_app`, which shadows the submodule when
    # accessed via `from app.tasks import celery_app` or `import app.tasks.celery_app as x`.
    import app.tasks.celery_app  # noqa: F401 — ensure submodule is in sys.modules

    module = sys.modules["app.tasks.celery_app"]
    importlib.reload(module)
    assert "test:6379" in module.celery_app.conf.broker_url


def test_celery_app_has_two_queues() -> None:
    """Spec § 4.1:default + llm 两个队列。"""
    from app.tasks.celery_app import celery_app

    queue_names = {q.name for q in celery_app.conf.task_queues or []}
    assert {"default", "llm"}.issubset(queue_names)


def test_celery_app_eager_when_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """L0/L1 测试用 CELERY_TASK_ALWAYS_EAGER=1 同步跑。"""
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    import app.tasks.celery_app  # noqa: F401

    module = sys.modules["app.tasks.celery_app"]
    importlib.reload(module)
    assert module.celery_app.conf.task_always_eager is True


def test_generate_session_title_routes_to_llm_queue() -> None:
    """C74: generate_session_title makes a real llm.chat call and must route to llm queue.

    Consistent with generate_detail_card; default queue is reserved for non-LLM work.
    """
    from app.tasks.celery_app import celery_app

    routes = celery_app.conf.task_routes or {}
    task_name = "app.tasks.title_generation.generate_session_title"
    assert task_name in routes, (
        f"{task_name} must have an explicit route entry (C74: LLM tasks belong on the llm queue)"
    )
    assert routes[task_name]["queue"] == "llm", (
        f"{task_name} must route to 'llm' queue, got {routes[task_name]['queue']!r}"
    )


def test_run_chat_routes_to_worker_llm_queue() -> None:
    """run_chat uses the LLM and its explicit queue must be consumed by the L2 worker."""
    from app.tasks.celery_app import celery_app

    from tests.conftest_celery import CELERY_WORKER_QUEUES

    routes = celery_app.conf.task_routes or {}
    task_name = "app.tasks.chat_runner.run_chat"
    assert task_name in routes
    assert routes[task_name]["queue"] == "llm"
    assert routes[task_name]["queue"] in CELERY_WORKER_QUEUES


@pytest.mark.parametrize("mode", ["mock", "cassette"])
def test_l2_worker_env_supplies_non_live_construction_key(mode: str) -> None:
    """Offline worker modes can build embeddings before marking chat running."""
    from tests.conftest_celery import prepare_celery_worker_env

    env = prepare_celery_worker_env(
        {"LLM_MODE": mode, "DASHSCOPE_API_KEY": ""},
        "redis://127.0.0.1:6379/15",
    )

    assert env["LLM_MODE"] == mode
    assert env["DASHSCOPE_API_KEY"] == "test-key-not-for-live-calls"
