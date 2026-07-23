from __future__ import annotations

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
