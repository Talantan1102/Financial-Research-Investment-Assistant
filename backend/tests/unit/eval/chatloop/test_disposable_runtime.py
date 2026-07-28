from __future__ import annotations

import asyncio
from hashlib import sha256
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


class _FakeMilvusClient:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self._collections: set[str] = set()

    def has_collection(self, collection_name: str) -> bool:
        return collection_name in self._collections

    def create_collection(self, *, collection_name: str, schema: object) -> None:
        assert schema is not None
        self._events.append(f"create_collection:{collection_name}")
        self._collections.add(collection_name)

    def create_index(self, *, collection_name: str, index_params: object) -> None:
        assert collection_name in self._collections
        assert index_params is not None
        self._events.append(f"create_index:{collection_name}")

    def load_collection(self, collection_name: str) -> None:
        assert collection_name in self._collections
        self._events.append(f"load_collection:{collection_name}")

    def release_collection(self, collection_name: str) -> None:
        self._events.append(f"release_collection:{collection_name}")

    def drop_collection(self, collection_name: str) -> None:
        self._events.append(f"drop_collection:{collection_name}")
        self._collections.remove(collection_name)

    def delete(self, *, collection_name: str, ids: list[str]) -> None:
        assert collection_name in self._collections
        self._events.append(f"delete:{collection_name}:{','.join(ids)}")

    def close(self) -> None:
        self._events.append("milvus_close")


class _FailingMilvusClient(_FakeMilvusClient):
    def __init__(self, events: list[str], *, fail_stage: str) -> None:
        super().__init__(events)
        self._fail_stage = fail_stage

    def create_collection(self, *, collection_name: str, schema: object) -> None:
        if self._fail_stage == "create":
            self._events.append(f"create_collection:{collection_name}")
            raise OSError("create failed")
        super().create_collection(collection_name=collection_name, schema=schema)

    def create_index(self, *, collection_name: str, index_params: object) -> None:
        if self._fail_stage == "index":
            self._events.append(f"create_index:{collection_name}")
            raise OSError("index failed")
        super().create_index(collection_name=collection_name, index_params=index_params)

    def load_collection(self, collection_name: str) -> None:
        if self._fail_stage == "load":
            self._events.append(f"load_collection:{collection_name}")
            raise OSError("load failed")
        super().load_collection(collection_name)


def _patch_memory_builders(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "eval.chatloop.disposable_runtime._build_memory_schema",
        lambda: object(),
    )
    monkeypatch.setattr(
        "eval.chatloop.disposable_runtime._build_memory_index_params",
        lambda: object(),
    )


def test_memory_isolation_never_drops_a_pre_existing_same_name_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    client = _FakeMilvusClient(events)
    runtime = DisposableEvalRuntime(
        admin_dsn="postgresql://unused/postgres",
        run_id="pre-existing-memory",
        database_name="fria_eval_pre_existing_memory",
    )
    runtime.state = RuntimeState.READY
    collection_name = f"chat_memory_eval_{sha256(runtime.run_id.encode()).hexdigest()[:24]}"
    client._collections.add(collection_name)
    _patch_memory_builders(monkeypatch)

    with pytest.raises(RuntimeError, match="already exists"):
        runtime.provision_memory_isolation(client_factory=lambda _uri: client)

    assert collection_name in client._collections
    assert not any(event.startswith("drop_collection:") for event in events)
    assert events == ["milvus_close"]


@pytest.mark.parametrize(
    ("fail_stage", "expect_drop"),
    [("create", False), ("index", True), ("load", True)],
)
def test_memory_isolation_failure_cleans_up_only_a_collection_created_by_this_runtime(
    monkeypatch: pytest.MonkeyPatch,
    fail_stage: str,
    expect_drop: bool,
) -> None:
    events: list[str] = []
    client = _FailingMilvusClient(events, fail_stage=fail_stage)
    runtime = DisposableEvalRuntime(
        admin_dsn="postgresql://unused/postgres",
        run_id=f"memory-{fail_stage}-failure",
        database_name=f"fria_eval_memory_{fail_stage}_failure",
    )
    runtime.state = RuntimeState.READY
    _patch_memory_builders(monkeypatch)

    with pytest.raises(OSError, match=f"{fail_stage} failed"):
        runtime.provision_memory_isolation(client_factory=lambda _uri: client)

    drop_events = [event for event in events if event.startswith("drop_collection:")]
    assert bool(drop_events) is expect_drop
    assert events[-1] == "milvus_close"


def test_memory_isolation_is_run_scoped_and_exported_to_child_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    client = _FakeMilvusClient(events)
    runtime = DisposableEvalRuntime(
        admin_dsn="postgresql://user:password@db.example:5432/postgres",
        run_id="memory-run/with unsafe chars",
        database_name="fria_eval_memory_run",
    )
    runtime.state = RuntimeState.READY
    monkeypatch.setattr(
        "eval.chatloop.disposable_runtime._build_memory_schema",
        lambda: object(),
    )
    monkeypatch.setattr(
        "eval.chatloop.disposable_runtime._build_memory_index_params",
        lambda: object(),
    )

    runtime.provision_memory_isolation(
        host="milvus.example",
        port=19530,
        client_factory=lambda _uri: client,
    )

    runtime.require_capabilities(memory=True)
    assert runtime.memory_client is client
    assert runtime.memory_collection_name.startswith("chat_memory_eval_")
    assert runtime.memory_collection_name in client._collections
    assert runtime.subprocess_env["CHAT_MEMORY_COLLECTION_NAME"] == (runtime.memory_collection_name)
    assert runtime.subprocess_env["MILVUS_HOST"] == "milvus.example"
    assert runtime.subprocess_env["MILVUS_PORT"] == "19530"


@pytest.mark.asyncio
async def test_memory_cleanup_deletes_only_requested_trial_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    client = _FakeMilvusClient(events)
    runtime = DisposableEvalRuntime(
        admin_dsn="postgresql://unused/postgres",
        run_id="memory-trial-cleanup",
        database_name="fria_eval_memory_trial_cleanup",
    )
    runtime.state = RuntimeState.READY
    monkeypatch.setattr(
        "eval.chatloop.disposable_runtime._build_memory_schema",
        lambda: object(),
    )
    monkeypatch.setattr(
        "eval.chatloop.disposable_runtime._build_memory_index_params",
        lambda: object(),
    )
    runtime.provision_memory_isolation(client_factory=lambda _uri: client)
    collection_name = runtime.memory_collection_name

    await runtime.cleanup_memory_mirrors(["edge-1", "edge-2"], ["ignored-node"])

    assert events[-1] == f"delete:{collection_name}:edge-1,edge-2"


@pytest.mark.asyncio
async def test_cleanup_drops_owned_memory_collection_before_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    client = _FakeMilvusClient(events)
    runtime = DisposableEvalRuntime(
        admin_dsn="postgresql://unused/postgres",
        run_id="memory-cleanup",
        database_name="fria_eval_memory_cleanup",
    )
    runtime.state = RuntimeState.READY
    monkeypatch.setattr(
        "eval.chatloop.disposable_runtime._build_memory_schema",
        lambda: object(),
    )
    monkeypatch.setattr(
        "eval.chatloop.disposable_runtime._build_memory_index_params",
        lambda: object(),
    )
    monkeypatch.setattr(runtime, "_drop_database", lambda: events.append("drop_database"))
    runtime.provision_memory_isolation(client_factory=lambda _uri: client)
    collection_name = runtime.memory_collection_name

    await runtime.aclose()

    assert events[-4:] == [
        f"release_collection:{collection_name}",
        f"drop_collection:{collection_name}",
        "milvus_close",
        "drop_database",
    ]
    assert runtime.state is RuntimeState.CLOSED


@pytest.mark.asyncio
async def test_memory_drop_failure_retains_collection_identity_for_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    client = _FakeMilvusClient(events)
    runtime = DisposableEvalRuntime(
        admin_dsn="postgresql://unused/postgres",
        run_id="memory-cleanup-failure",
        database_name="fria_eval_memory_cleanup_failure",
    )
    runtime.state = RuntimeState.READY
    monkeypatch.setattr(
        "eval.chatloop.disposable_runtime._build_memory_schema",
        lambda: object(),
    )
    monkeypatch.setattr(
        "eval.chatloop.disposable_runtime._build_memory_index_params",
        lambda: object(),
    )
    monkeypatch.setattr(runtime, "_drop_database", lambda: events.append("drop_database"))
    runtime.provision_memory_isolation(client_factory=lambda _uri: client)
    collection_name = runtime.memory_collection_name

    def fail_drop(_collection_name: str) -> None:
        raise OSError("milvus drop failed")

    monkeypatch.setattr(client, "drop_collection", fail_drop)

    with pytest.raises(RuntimeCleanupError) as captured:
        await runtime.aclose()

    assert [failure.stage for failure in captured.value.failures] == ["memory_collection"]
    assert collection_name in client._collections
    assert runtime._memory_collection_name == collection_name
    assert runtime._memory_client is client
    assert captured.value.memory_leaked is True
    assert captured.value.memory_collection_name == collection_name
    assert runtime.state is RuntimeState.LEAKED


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
