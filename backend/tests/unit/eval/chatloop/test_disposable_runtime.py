from __future__ import annotations

import asyncio
from typing import Any

import pytest
from eval.chatloop.disposable_runtime import (
    DisposableEvalRuntime,
    RuntimeCleanupError,
    RuntimeState,
)


class _FailingDriver:
    is_open = True

    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def aclose(self) -> None:
        self._events.append("durable_driver")
        raise OSError("offline failed")


class _FailingAsyncEngine:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def dispose(self) -> None:
        self._events.append("async_engine")
        raise OSError("async dispose failed")


class _FailingSyncEngine:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def dispose(self) -> None:
        self._events.append("sync_engine")
        raise OSError("sync dispose failed")


class _WaitingDriver:
    is_open = True

    def __init__(self, events: list[str], started: asyncio.Event) -> None:
        self._events = events
        self._started = started

    async def aclose(self) -> None:
        self._events.append("durable_driver")
        self._started.set()
        await asyncio.Event().wait()


class _RecordingAsyncEngine:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def dispose(self) -> None:
        self._events.append("async_engine")


class _RecordingFailingSyncEngine:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def dispose(self) -> None:
        self._events.append("sync_engine")
        raise OSError("sync cleanup also failed")


@pytest.mark.asyncio
async def test_cleanup_attempts_every_stage_and_reports_removed_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    runtime = DisposableEvalRuntime(
        admin_dsn="postgresql://unused/postgres",
        run_id="unit-cleanup",
        database_name="fria_eval_unit_cleanup",
    )
    runtime.state = RuntimeState.READY
    runtime._durable_driver = _FailingDriver(events)
    runtime._async_engine = _FailingAsyncEngine(events)
    runtime._sync_engine = _FailingSyncEngine(events)
    monkeypatch.setattr(runtime, "_drop_database", lambda: events.append("drop_database"))

    with pytest.raises(RuntimeCleanupError) as captured:
        await runtime.aclose()

    assert events == ["durable_driver", "async_engine", "sync_engine", "drop_database"]
    assert [failure.stage for failure in captured.value.failures] == [
        "durable_driver",
        "async_engine",
        "sync_engine",
    ]
    assert captured.value.database_leaked is False
    assert runtime.state is RuntimeState.CLOSED


@pytest.mark.asyncio
async def test_cleanup_marks_leaked_only_when_drop_cannot_be_proven(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = DisposableEvalRuntime(
        admin_dsn="postgresql://unused/postgres",
        run_id="unit-leak",
        database_name="fria_eval_unit_leak",
    )
    runtime.state = RuntimeState.READY

    def fail_drop() -> Any:
        raise OSError("drop failed")

    monkeypatch.setattr(runtime, "_drop_database", fail_drop)

    with pytest.raises(RuntimeCleanupError) as captured:
        await runtime.aclose()

    assert captured.value.database_leaked is True
    assert [failure.stage for failure in captured.value.failures] == ["drop_database"]
    assert runtime.state is RuntimeState.LEAKED


@pytest.mark.asyncio
async def test_cancellation_still_disposes_and_drops_then_propagates_original_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    started = asyncio.Event()
    runtime = DisposableEvalRuntime(
        admin_dsn="postgresql://unused/postgres",
        run_id="unit-cancel-cleanup",
        database_name="fria_eval_unit_cancel_cleanup",
    )
    runtime.state = RuntimeState.READY
    runtime._durable_driver = _WaitingDriver(events, started)
    runtime._async_engine = _RecordingAsyncEngine(events)
    runtime._sync_engine = _RecordingFailingSyncEngine(events)
    monkeypatch.setattr(runtime, "_drop_database", lambda: events.append("drop_database"))

    cleanup = asyncio.create_task(runtime.aclose())
    await started.wait()
    cleanup.cancel()
    with pytest.raises(asyncio.CancelledError) as captured:
        await cleanup

    assert events == ["durable_driver", "async_engine", "sync_engine", "drop_database"]
    assert runtime.state is RuntimeState.CLOSED
    assert any("sync_engine" in note for note in getattr(captured.value, "__notes__", []))


@pytest.mark.asyncio
async def test_drop_failure_takes_priority_over_cleanup_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    started = asyncio.Event()
    runtime = DisposableEvalRuntime(
        admin_dsn="postgresql://unused/postgres",
        run_id="unit-cancel-leak",
        database_name="fria_eval_unit_cancel_leak",
    )
    runtime.state = RuntimeState.READY
    runtime._durable_driver = _WaitingDriver(events, started)
    runtime._async_engine = _RecordingAsyncEngine(events)

    def fail_drop() -> None:
        events.append("drop_database")
        raise OSError("drop still failed")

    monkeypatch.setattr(runtime, "_drop_database", fail_drop)
    cleanup = asyncio.create_task(runtime.aclose())
    await started.wait()
    cleanup.cancel()

    with pytest.raises(RuntimeCleanupError) as captured:
        await cleanup

    assert captured.value.database_leaked is True
    assert runtime.state is RuntimeState.LEAKED
    assert events == ["durable_driver", "async_engine", "drop_database"]
