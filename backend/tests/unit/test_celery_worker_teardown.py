from __future__ import annotations

import io
import signal
import subprocess
from unittest.mock import MagicMock

import pytest


def test_posix_worker_teardown_terminates_process_group(monkeypatch) -> None:
    from tests import conftest_celery

    proc = MagicMock(pid=4321)
    monkeypatch.setattr(conftest_celery.os, "getpgid", lambda _pid: 9876, raising=False)
    killpg = MagicMock()
    monkeypatch.setattr(conftest_celery.os, "killpg", killpg, raising=False)

    conftest_celery._stop_posix_worker(proc)

    killpg.assert_called_once_with(9876, signal.SIGTERM)
    proc.wait.assert_called_once_with(timeout=10)


def test_posix_worker_teardown_escalates_entire_group(monkeypatch) -> None:
    from tests import conftest_celery

    proc = MagicMock(pid=4321)
    proc.wait.side_effect = [subprocess.TimeoutExpired("celery", 10), 0]
    monkeypatch.setattr(conftest_celery.os, "getpgid", lambda _pid: 9876, raising=False)
    killpg = MagicMock()
    monkeypatch.setattr(conftest_celery.os, "killpg", killpg, raising=False)

    conftest_celery._stop_posix_worker(proc)

    assert killpg.call_args_list[0].args == (9876, signal.SIGTERM)
    assert killpg.call_args_list[1].args == (9876, getattr(signal, "SIGKILL", 9))


def test_windows_worker_teardown_kills_tree_and_reaps_process(monkeypatch) -> None:
    from tests import conftest_celery

    proc = MagicMock(pid=4321)
    run = MagicMock()
    monkeypatch.setattr(conftest_celery.sys, "platform", "win32")
    monkeypatch.setattr(conftest_celery.subprocess, "run", run)

    conftest_celery._stop_worker(proc)

    run.assert_called_once_with(
        ["taskkill", "/PID", "4321", "/T", "/F"],
        capture_output=True,
        check=False,
    )
    proc.wait.assert_called_once_with(timeout=10)


def test_worker_spawn_failure_restores_producer_configuration(monkeypatch) -> None:
    from tests import conftest_celery

    producer_config = MagicMock()
    monkeypatch.setattr(
        conftest_celery.subprocess,
        "Popen",
        MagicMock(side_effect=OSError("spawn failed")),
    )

    with pytest.raises(OSError, match="spawn failed"):
        conftest_celery._start_worker(producer_config, ["celery"])

    producer_config.__exit__.assert_called_once()
    assert producer_config.__exit__.call_args.args[0] is OSError


def test_worker_teardown_restores_producer_when_stop_raises(monkeypatch) -> None:
    from app.tasks.celery_app import celery_app

    from tests import conftest_celery

    original = (
        celery_app.conf.broker_url,
        celery_app.conf.result_backend,
        celery_app._backend_cache,
    )
    backend_marker = object()
    celery_app._backend_cache = backend_marker
    proc = MagicMock()
    proc.stdout = io.BytesIO(b"celery@test ready\n")
    monkeypatch.setattr(conftest_celery, "_start_worker", lambda *_args, **_kwargs: proc)
    monkeypatch.setattr(
        conftest_celery,
        "_stop_worker",
        MagicMock(side_effect=OSError("stop failed")),
    )
    worker = conftest_celery.celery_worker_subprocess.__wrapped__(
        "redis://127.0.0.1:6399/14",
        None,
    )

    try:
        next(worker)
        with pytest.raises(OSError, match="stop failed"):
            worker.close()
        assert celery_app.conf.broker_url == original[0]
        assert celery_app.conf.result_backend == original[1]
        assert celery_app._backend_cache is backend_marker
    finally:
        celery_app.conf.broker_url = original[0]
        celery_app.conf.result_backend = original[1]
        celery_app._backend_cache = original[2]


def test_worker_ready_timeout_restores_producer_after_repeated_wait_timeout(
    monkeypatch,
) -> None:
    from app.tasks.celery_app import celery_app

    from tests import conftest_celery

    original = (
        celery_app.conf.broker_url,
        celery_app.conf.result_backend,
        celery_app._backend_cache,
    )
    backend_marker = object()
    celery_app._backend_cache = backend_marker
    proc = MagicMock(pid=4321)
    proc.stdout = io.BytesIO(b"")
    proc.poll.return_value = 1
    proc.wait.side_effect = [
        subprocess.TimeoutExpired("celery", 10),
        subprocess.TimeoutExpired("celery", 10),
    ]
    monkeypatch.setattr(conftest_celery, "_start_worker", lambda *_args, **_kwargs: proc)
    monkeypatch.setattr(conftest_celery.sys, "platform", "win32")
    monkeypatch.setattr(conftest_celery.subprocess, "run", MagicMock())
    worker = conftest_celery.celery_worker_subprocess.__wrapped__(
        "redis://127.0.0.1:6399/14",
        None,
    )

    try:
        with pytest.raises(subprocess.TimeoutExpired):
            next(worker)
        assert celery_app.conf.broker_url == original[0]
        assert celery_app.conf.result_backend == original[1]
        assert celery_app._backend_cache is backend_marker
    finally:
        celery_app.conf.broker_url = original[0]
        celery_app.conf.result_backend = original[1]
        celery_app._backend_cache = original[2]
