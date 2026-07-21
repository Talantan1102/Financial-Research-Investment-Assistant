from __future__ import annotations

import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from tests.helpers.run_control_compose_harness import (
    ComposeCleanupError,
    ComposeRunControlHarness,
)


class CleanupRunner:
    def __init__(self, *, permanent_failure: bool = False) -> None:
        self.permanent_failure = permanent_failure
        self.down_calls = 0

    def __call__(
        self, arguments: tuple[str, ...], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        del kwargs
        command = tuple(arguments)
        if "down" in command:
            self.down_calls += 1
            failed = self.permanent_failure or self.down_calls == 1
            return subprocess.CompletedProcess(
                command,
                1 if failed else 0,
                stdout="partial cleanup" if failed else "removed",
                stderr="daemon busy" if failed else "",
            )
        leftover = "container-id\n" if self.permanent_failure and "ps" in command else ""
        return subprocess.CompletedProcess(command, 0, stdout=leftover, stderr="")


def test_cleanup_retries_first_down_failure_then_audits_empty(tmp_path: Path) -> None:
    runner = CleanupRunner()
    harness = ComposeRunControlHarness(
        tmp_path,
        runner=runner,
        cleanup_attempts=2,
        cleanup_retry_delay=0,
    )

    harness._cleanup()

    assert runner.down_calls == 2


def test_cleanup_reports_permanent_failure_with_output_and_leftovers(tmp_path: Path) -> None:
    runner = CleanupRunner(permanent_failure=True)
    harness = ComposeRunControlHarness(
        tmp_path,
        runner=runner,
        cleanup_attempts=2,
        cleanup_retry_delay=0,
    )

    with pytest.raises(ComposeCleanupError) as caught:
        harness._cleanup()

    message = str(caught.value)
    assert "daemon busy" in message
    assert "partial cleanup" in message
    assert "container-id" in message
    assert "attempt=2" in message


def test_injected_failure_after_up_still_runs_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = ComposeRunControlHarness(tmp_path)
    cleanup_called = False

    monkeypatch.setenv("RUN_CONTROL_INJECT_FAILURE_AFTER_UP", "1")
    monkeypatch.setattr(harness, "_compose", lambda *args, **kwargs: "")
    monkeypatch.setattr(harness, "_assert_processes_healthy", lambda: None)

    def cleanup() -> None:
        nonlocal cleanup_called
        cleanup_called = True

    monkeypatch.setattr(harness, "_cleanup", cleanup)

    with pytest.raises(RuntimeError, match="injected failure after Compose up"):
        harness.run()

    assert cleanup_called is True


def test_wait_outbox_by_id_queries_only_the_captured_row(tmp_path: Path) -> None:
    outbox_id = uuid4()
    calls: list[tuple[str, tuple[object, ...]]] = []

    class Cursor:
        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def execute(self, query: str, parameters: tuple[object, ...]) -> None:
            calls.append((query, parameters))

        def fetchone(self) -> tuple[int, bool, bool]:
            return (1, True, True)

    class Connection:
        def cursor(self) -> Cursor:
            return Cursor()

    @contextmanager
    def connect():
        yield Connection()

    harness = ComposeRunControlHarness(tmp_path)
    harness._connect = connect  # type: ignore[method-assign]

    row = harness._wait_outbox_by_id(
        outbox_id,
        lambda facts: facts == (1, True, True),
        select="delivery_attempts,delivered_at IS NOT NULL,acknowledged_at IS NOT NULL",
    )

    assert row == (1, True, True)
    assert calls == [
        (
            "SELECT delivery_attempts,delivered_at IS NOT NULL,"
            "acknowledged_at IS NOT NULL FROM run_outbox WHERE id=%s",
            (outbox_id,),
        )
    ]
