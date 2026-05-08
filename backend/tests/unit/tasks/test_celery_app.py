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
