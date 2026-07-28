from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from app.chatloop.run_executor import (
    CompletedResult,
    ExecuteChatRun,
    PauseResult,
    RunUsage,
)
from app.models.run import Run, RunAttempt, RunMessage, RunPause
from app.models.run_scheduling import RunWorker
from app.processes.run_api import create_run_api_app
from eval.chatloop.case_loader import load_catalog
from eval.chatloop.disposable_runtime import (
    DisposableEvalRuntime,
    RuntimeCleanupError,
    RuntimeState,
)
from eval.chatloop.durable_runtime import InProcessDurableDriver
from eval.chatloop.environment import CaseEnvironmentManager
from eval.chatloop.sut_runner import DurableRunHttpTransport
from sqlalchemy import select


def _admin_dsn(pg_test_container: dict[str, object]) -> str:
    return (
        f"postgresql://{pg_test_container['user']}:{pg_test_container['password']}"
        f"@{pg_test_container['host']}:{pg_test_container['port']}/postgres"
    )


def _database_exists(admin_dsn: str, name: str) -> bool:
    with (
        psycopg.connect(admin_dsn, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
        return cursor.fetchone() is not None


def _usage() -> RunUsage:
    return RunUsage("eval", "scripted", 2, 1, 0, 3, 0.0)


class _CompletedExecutor:
    def __init__(self, commands: list[ExecuteChatRun]) -> None:
        self._commands = commands

    async def execute(self, command: ExecuteChatRun) -> CompletedResult:
        self._commands.append(command)
        return CompletedResult(
            run_id=command.run_id,
            attempt_id=command.attempt_id,
            session_id=command.session_id,
            final_text="脚本执行完成",
            usage=_usage(),
            tools=(),
            events=(),
        )


class _PauseThenCompletedExecutor:
    def __init__(self, commands: list[ExecuteChatRun]) -> None:
        self._commands = commands

    async def execute(self, command: ExecuteChatRun) -> CompletedResult | PauseResult:
        self._commands.append(command)
        if len(self._commands) == 1:
            return PauseResult(
                run_id=command.run_id,
                attempt_id=command.attempt_id,
                session_id=command.session_id,
                pause_type="input",
                request={"tool_name": "ask_user", "question": "请确认继续"},
                continuation={"key_id": "eval-v1"},
                usage=_usage(),
                tools=(),
                events=(),
            )
        return CompletedResult(
            run_id=command.run_id,
            attempt_id=command.attempt_id,
            session_id=command.session_id,
            final_text="恢复后完成",
            usage=_usage(),
            tools=(),
            events=(),
        )


@pytest.mark.asyncio
async def test_in_process_durable_driver_completes_real_trial_run_and_cleans_runtime(
    pg_test_container: dict[str, object],
) -> None:
    admin_dsn = _admin_dsn(pg_test_container)
    runtime = DisposableEvalRuntime.provision(
        admin_dsn=admin_dsn,
        run_id=f"durable-smoke-{uuid4().hex}",
    )
    database_name = runtime.database_name
    commands: list[ExecuteChatRun] = []

    def executor_builder(*_args: Any) -> _CompletedExecutor:
        return _CompletedExecutor(commands)

    driver: InProcessDurableDriver | None = None
    try:
        driver = await InProcessDurableDriver.create(
            runtime.async_session_factory,
            executor_builder=executor_builder,
        )
        runtime.bind_durable_driver(driver)
        manager = CaseEnvironmentManager(runtime)
        case = load_catalog().by_id("B6-06")
        manager.require_execution_capabilities(case)
        environment = await manager.prepare(case, trial_index=0)
        actor = environment.actor("requester")
        assert actor.user_id is not None

        app = create_run_api_app(session_factory=runtime.async_session_factory)
        transport = DurableRunHttpTransport(
            runtime.async_session_factory,
            actor=actor,
            tenant_id=environment.tenant_id,
            client_transport=httpx.ASGITransport(app=app),
            progress_callback=driver.advance,
            timeout_s=5,
        )
        observed = await transport.execute_messages(
            case_id=case.case_id,
            messages=list(case.user_messages),
            run_idx=0,
        )

        assert observed.run_state["status"] == "completed"
        assert observed.response_text == "脚本执行完成"
        assert len(commands) == 1
        assert str(commands[0].run_id) == observed.run_id
        async with runtime.async_session_factory() as session:
            run = await session.get(Run, UUID(observed.run_id))
            attempts = tuple(
                await session.scalars(
                    select(RunAttempt).where(RunAttempt.run_id == UUID(observed.run_id))
                )
            )
            final_message = (
                None
                if run is None or run.final_message_id is None
                else await session.get(RunMessage, run.final_message_id)
            )
        assert run is not None
        assert run.status == "completed"
        assert run.tenant_id == environment.tenant_id
        assert run.created_by_user_id == actor.user_id
        assert len(attempts) == 1
        assert attempts[0].worker_id == driver.worker_id
        assert attempts[0].status == "completed"
        assert final_message is not None
        assert final_message.content == "脚本执行完成"
        assert driver.completed_advances == 1

        await driver.aclose()
        async with runtime.async_session_factory() as session:
            worker = await session.get(RunWorker, driver.worker_id)
        assert worker is not None
        assert worker.status == "offline"
    finally:
        if driver is not None:
            await driver.aclose()
        await runtime.aclose()

    assert runtime.state is RuntimeState.CLOSED
    assert not _database_exists(admin_dsn, database_name)


@pytest.mark.asyncio
async def test_progress_callback_can_advance_pause_resume_into_a_new_attempt(
    pg_test_container: dict[str, object],
) -> None:
    admin_dsn = _admin_dsn(pg_test_container)
    runtime = DisposableEvalRuntime.provision(
        admin_dsn=admin_dsn,
        run_id=f"durable-resume-{uuid4().hex}",
    )
    commands: list[ExecuteChatRun] = []

    def executor_builder(*_args: Any) -> _PauseThenCompletedExecutor:
        return _PauseThenCompletedExecutor(commands)

    driver: InProcessDurableDriver | None = None
    try:
        driver = await InProcessDurableDriver.create(
            runtime.async_session_factory,
            executor_builder=executor_builder,
        )
        runtime.bind_durable_driver(driver)
        manager = CaseEnvironmentManager(runtime)
        case = load_catalog().by_id("B6-06")
        manager.require_execution_capabilities(case)
        environment = await manager.prepare(case, trial_index=1)
        actor = environment.actor("requester")

        transport = DurableRunHttpTransport(
            runtime.async_session_factory,
            actor=actor,
            tenant_id=environment.tenant_id,
            client_transport=httpx.ASGITransport(
                app=create_run_api_app(session_factory=runtime.async_session_factory)
            ),
            progress_callback=driver.advance,
            timeout_s=5,
        )
        observed = await transport.execute_messages(
            case_id=case.case_id,
            messages=[case.user_messages[0], "继续"],
            run_idx=1,
        )

        async with runtime.async_session_factory() as session:
            attempts = tuple(
                await session.scalars(
                    select(RunAttempt)
                    .where(RunAttempt.run_id == UUID(observed.run_id))
                    .order_by(RunAttempt.attempt_no)
                )
            )
            pause = await session.scalar(
                select(RunPause).where(RunPause.run_id == UUID(observed.run_id))
            )
        assert observed.run_state["status"] == "completed"
        assert observed.response_text == "恢复后完成"
        assert len(commands) == 2
        assert [attempt.status for attempt in attempts] == ["paused", "completed"]
        assert len({attempt.id for attempt in attempts}) == 2
        assert all(attempt.worker_id == driver.worker_id for attempt in attempts)
        assert pause is not None
        assert pause.resolved_at is not None
        assert pause.response_payload == {"text": "继续"}
        assert driver.completed_advances == 2
    finally:
        if driver is not None:
            await driver.aclose()
        await runtime.aclose()

    assert not _database_exists(admin_dsn, runtime.database_name)


def test_durable_capability_rejects_arbitrary_binding(
    pg_test_container: dict[str, object],
) -> None:
    runtime = DisposableEvalRuntime.provision(
        admin_dsn=_admin_dsn(pg_test_container),
        run_id=f"durable-binding-{uuid4().hex}",
    )
    try:
        with pytest.raises(TypeError, match="InProcessDurableDriver"):
            runtime.bind_durable_driver(object())
        with pytest.raises(RuntimeError, match="durable stack isolation"):
            runtime.require_capabilities(durable=True)
    finally:
        runtime.close()


@pytest.mark.asyncio
async def test_runtime_still_drops_database_when_worker_offline_fails(
    pg_test_container: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_dsn = _admin_dsn(pg_test_container)
    runtime = DisposableEvalRuntime.provision(
        admin_dsn=admin_dsn,
        run_id=f"durable-cleanup-{uuid4().hex}",
    )
    database_name = runtime.database_name

    def executor_builder(*_args: Any) -> _CompletedExecutor:
        return _CompletedExecutor([])

    driver = await InProcessDurableDriver.create(
        runtime.async_session_factory,
        executor_builder=executor_builder,
    )
    runtime.bind_durable_driver(driver)

    async def fail_mark_offline(_worker_id: UUID) -> None:
        raise OSError("worker registry unavailable")

    monkeypatch.setattr(driver._registry, "mark_offline", fail_mark_offline)

    with pytest.raises(RuntimeCleanupError) as captured:
        await runtime.aclose()

    assert captured.value.database_leaked is False
    assert [failure.stage for failure in captured.value.failures] == ["durable_driver"]
    assert runtime.state is RuntimeState.CLOSED
    assert not _database_exists(admin_dsn, database_name)


@pytest.mark.asyncio
async def test_hanging_progress_callback_is_bounded_by_run_timeout(
    pg_test_container: dict[str, object],
) -> None:
    admin_dsn = _admin_dsn(pg_test_container)
    runtime = DisposableEvalRuntime.provision(
        admin_dsn=admin_dsn,
        run_id=f"durable-progress-timeout-{uuid4().hex}",
    )
    driver: InProcessDurableDriver | None = None
    callback_finished = asyncio.Event()
    active_callback_tasks: set[asyncio.Task[Any]] = set()
    try:
        driver = await InProcessDurableDriver.create(
            runtime.async_session_factory,
            executor_builder=lambda *_args: _CompletedExecutor([]),
        )
        runtime.bind_durable_driver(driver)
        manager = CaseEnvironmentManager(runtime)
        case = load_catalog().by_id("B6-06")
        manager.require_execution_capabilities(case)
        environment = await manager.prepare(case, trial_index=2)

        async def hang_forever() -> None:
            task = asyncio.current_task()
            assert task is not None
            active_callback_tasks.add(task)
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await asyncio.sleep(0.02)
                raise
            finally:
                active_callback_tasks.remove(task)
                callback_finished.set()

        transport = DurableRunHttpTransport(
            runtime.async_session_factory,
            actor=environment.actor("requester"),
            tenant_id=environment.tenant_id,
            client_transport=httpx.ASGITransport(
                app=create_run_api_app(session_factory=runtime.async_session_factory)
            ),
            progress_callback=hang_forever,
            timeout_s=0.05,
        )
        started = time.monotonic()
        with pytest.raises(TimeoutError, match="progress callback.*remaining timeout"):
            await transport.execute_messages(
                case_id=case.case_id,
                messages=list(case.user_messages),
                run_idx=2,
            )
        assert time.monotonic() - started < 1.0
        assert callback_finished.is_set()
        assert active_callback_tasks == set()
    finally:
        if driver is not None:
            await driver.aclose()
        await runtime.aclose()
