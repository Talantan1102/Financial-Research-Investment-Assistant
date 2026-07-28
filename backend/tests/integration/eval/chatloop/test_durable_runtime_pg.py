from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import eval.chatloop.durable_runtime as durable_runtime_module
import httpx
import psycopg
import pytest
from app.chatloop.gates import GateConfig
from app.chatloop.run_executor import (
    CompletedResult,
    ExecuteChatRun,
    PauseResult,
    RunUsage,
)
from app.chatloop.tool_hub import ToolHub
from app.models.run import Run, RunAttempt, RunMessage, RunPause
from app.models.run_execution import RunUsageRecord
from app.models.run_scheduling import RunWorker
from app.processes.run_api import create_run_api_app
from app.services.llm_step import StepResult, StepToolCall
from app.services.run_chat_worker import (
    ToolRiskPolicy,
    build_chat_executor_builder,
)
from app.tools.base import Tool, ToolError
from eval.chatloop.business_runner import (
    BusinessExecutionContext,
    DurableHttpBusinessExecutor,
)
from eval.chatloop.case_loader import load_catalog
from eval.chatloop.disposable_runtime import (
    DisposableEvalRuntime,
    RuntimeCleanupError,
    RuntimeState,
)
from eval.chatloop.durable_runtime import InProcessDurableDriver
from eval.chatloop.environment import CaseEnvironmentManager
from eval.chatloop.faults import DeterministicBarrier, TransportFaultPlan
from eval.chatloop.sut_runner import DurableRunHttpTransport
from pydantic import BaseModel
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


def _usage(
    *,
    input_tokens: int = 2,
    output_tokens: int = 1,
    cost_cny: float = 0.0,
) -> RunUsage:
    return RunUsage(
        "eval",
        "scripted",
        input_tokens,
        output_tokens,
        0,
        input_tokens + output_tokens,
        cost_cny,
    )


class _QueryArgs(BaseModel):
    query: str


class _SuccessfulReadTool(Tool):
    name = "memory_search"
    description = "return the requested value"
    args_schema = _QueryArgs

    async def run(self, args: _QueryArgs) -> dict[str, Any]:
        return {"answer": args.query}


class _FailedReadTool(Tool):
    name = "read_cached_result"
    description = "fail with an explicit business-safe error"
    args_schema = _QueryArgs

    async def run(self, args: _QueryArgs) -> dict[str, Any]:
        raise ToolError(f"forced failure for {args.query}")


class _RecordingScriptedLLM:
    provider = "scripted"
    default_model = "scripted-v1"

    def __init__(self) -> None:
        self.received_messages: list[list[dict[str, Any]]] = []
        self._step = 0

    async def stream_step(self, **kwargs: Any) -> StepResult:
        self.received_messages.append([dict(message) for message in kwargs["messages"]])
        self._step += 1
        if self._step == 1:
            return StepResult(
                content="",
                tool_calls=[
                    StepToolCall(
                        id="call-success",
                        name="memory_search",
                        arguments='{"query":"position"}',
                    ),
                    StepToolCall(
                        id="call-failure",
                        name="read_cached_result",
                        arguments='{"query":"missing"}',
                    ),
                ],
                finish_reason="tool_calls",
                prompt_tokens=4,
                completion_tokens=3,
                cached_tokens=0,
                cost_cny=0.01,
            )
        return StepResult(
            content="scripted durable answer",
            tool_calls=[],
            finish_reason="stop",
            prompt_tokens=5,
            completion_tokens=2,
            cached_tokens=0,
            cost_cny=0.02,
        )


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
                usage=_usage(input_tokens=2, output_tokens=1, cost_cny=0.01),
                tools=(),
                events=(),
            )
        return CompletedResult(
            run_id=command.run_id,
            attempt_id=command.attempt_id,
            session_id=command.session_id,
            final_text="恢复后完成",
            usage=_usage(input_tokens=5, output_tokens=2, cost_cny=0.02),
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
async def test_lazy_driver_runs_real_chatloop_stack_and_projects_trace_observation(
    pg_test_container: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_dsn = _admin_dsn(pg_test_container)
    runtime = DisposableEvalRuntime.provision(
        admin_dsn=admin_dsn,
        run_id=f"durable-chatloop-{uuid4().hex}",
    )
    llm = _RecordingScriptedLLM()
    resource_events: list[str] = []

    def components(_singletons: Any, **_kwargs: Any) -> Any:
        hub = ToolHub()
        hub.register_inprocess([_SuccessfulReadTool(), _FailedReadTool()])
        return SimpleNamespace(
            llm=llm,
            tool_hub=hub,
            gate_cfg=GateConfig(),
            skill_listing="",
            system_prompt="durable eval assistant",
        )

    monkeypatch.setattr("app.chatloop.worker_wiring.build_turn_components", components)

    async def resource_factory() -> tuple[Any, Any]:
        resource_events.append("start")
        builder = build_chat_executor_builder(
            object(),
            provider="scripted",
            model="scripted-v1",
            risk_policy=ToolRiskPolicy.from_trusted_names({"memory_search", "read_cached_result"}),
        )

        async def cleanup() -> None:
            resource_events.append("close")

        return builder, cleanup

    driver = InProcessDurableDriver.lazy(
        runtime.async_session_factory,
        resource_factory=resource_factory,
    )
    runtime.bind_durable_driver(driver)
    case = load_catalog().by_id("B6-06")
    manager = CaseEnvironmentManager(runtime)
    manager.require_execution_capabilities(case)
    assert resource_events == []
    environment = await manager.prepare(case, trial_index=9)
    actor = environment.actor("requester")
    executor = DurableHttpBusinessExecutor(
        runtime.async_session_factory,
        base_url="http://run-api",
        timeout_s=5,
        client_transport=httpx.ASGITransport(
            app=create_run_api_app(session_factory=runtime.async_session_factory)
        ),
        progress_callback=driver.advance,
    )
    context = BusinessExecutionContext(
        case=case,
        environment=environment,
        actor=actor,
        fault_plans=(),
        transport_fault=TransportFaultPlan(),
        barrier=DeterministicBarrier(),
        execution_id="durable-chatloop-integration",
    )

    try:
        observation = await executor.execute(context)

        assert resource_events == ["start"]
        assert llm.received_messages
        assert any(
            message.get("content") == case.user_messages[0] for message in llm.received_messages[0]
        )
        assert observation.run_state["status"] == "completed"
        assert observation.evidence["response_text"] == "scripted durable answer"
        assert observation.evidence["execution_path"] == "durable"
        assert observation.total_tokens == 14
        assert observation.cost_cny == pytest.approx(0.03)
        assert observation.transcript[-1] == {
            "role": "assistant",
            "content": "scripted durable answer",
        }
        ledger = {row["tool_name"]: row for row in observation.tool_ledger}
        assert ledger["memory_search"] == {
            "tool_name": "memory_search",
            "arguments": {"query": "position"},
            "result": {"answer": "position"},
            "error": None,
            "status": "completed",
            "error_code": None,
            "error_message": None,
            "permission_decision": "direct",
            "permission_decisions": ["direct"],
            "idempotency_key": "call-success",
        }
        assert ledger["read_cached_result"]["arguments"] == {"query": "missing"}
        assert ledger["read_cached_result"]["result"] is None
        assert ledger["read_cached_result"]["status"] == "failed"
        assert ledger["read_cached_result"]["error_code"] == "tool_error"
        assert "forced failure for missing" in ledger["read_cached_result"]["error"]
        assert ledger["read_cached_result"]["permission_decisions"] == ["direct"]
        run_id = UUID(observation.run_state["run_ids"][0])
        async with runtime.async_session_factory() as session:
            run = await session.get(Run, run_id)
            attempts = tuple(
                await session.scalars(select(RunAttempt).where(RunAttempt.run_id == run_id))
            )
            messages = tuple(
                await session.scalars(
                    select(RunMessage).where(RunMessage.session_id == run.session_id)
                )
            )
            usage = await session.scalar(
                select(RunUsageRecord).where(RunUsageRecord.run_id == run_id)
            )
        assert run is not None and run.status == "completed"
        assert len(attempts) == 1 and attempts[0].status == "completed"
        assert {message.role for message in messages} >= {"user", "assistant"}
        assert usage is not None and usage.total_tokens == 14
    finally:
        await environment.cleanup()
        await runtime.aclose()

    assert resource_events == ["start", "close"]
    assert not _database_exists(admin_dsn, runtime.database_name)


@pytest.mark.asyncio
async def test_lazy_driver_concurrent_start_initializes_resources_once(
    pg_test_container: dict[str, object],
) -> None:
    runtime = DisposableEvalRuntime.provision(
        admin_dsn=_admin_dsn(pg_test_container),
        run_id=f"durable-lazy-start-{uuid4().hex}",
    )
    starts = 0
    closes = 0

    async def resource_factory() -> tuple[Any, Any]:
        nonlocal starts
        starts += 1
        await asyncio.sleep(0)

        async def cleanup() -> None:
            nonlocal closes
            closes += 1

        return (lambda *_args: _CompletedExecutor([])), cleanup

    driver = InProcessDurableDriver.lazy(
        runtime.async_session_factory,
        resource_factory=resource_factory,
    )
    runtime.bind_durable_driver(driver)
    try:
        await asyncio.gather(driver.start(), driver.start())
        assert starts == 1
        assert driver.is_started is True
    finally:
        await runtime.aclose()

    assert closes == 1


@pytest.mark.asyncio
async def test_lazy_driver_start_failure_makes_runtime_preflight_fail_closed(
    pg_test_container: dict[str, object],
) -> None:
    runtime = DisposableEvalRuntime.provision(
        admin_dsn=_admin_dsn(pg_test_container),
        run_id=f"durable-lazy-failure-{uuid4().hex}",
    )

    async def fail_resources() -> tuple[Any, Any]:
        raise RuntimeError("resource factory failed")

    driver = InProcessDurableDriver.lazy(
        runtime.async_session_factory,
        resource_factory=fail_resources,
    )
    runtime.bind_durable_driver(driver)
    runtime.require_capabilities(durable=True)

    try:
        with pytest.raises(RuntimeError, match="resource factory failed"):
            await driver.start()
        assert driver.is_open is False
        with pytest.raises(RuntimeError, match="durable stack isolation"):
            runtime.require_capabilities(durable=True)
    finally:
        await runtime.aclose()


@pytest.mark.asyncio
async def test_aclose_cancellation_waits_for_cleanup_without_orphan_task(
    pg_test_container: dict[str, object],
) -> None:
    runtime = DisposableEvalRuntime.provision(
        admin_dsn=_admin_dsn(pg_test_container),
        run_id=f"durable-cancel-cleanup-{uuid4().hex}",
    )
    cleanup_started = asyncio.Event()
    allow_cleanup_finish = asyncio.Event()
    cleanup_finished = asyncio.Event()
    cleanup_task: asyncio.Task[Any] | None = None

    async def resource_factory() -> tuple[Any, Any]:
        async def cleanup() -> None:
            nonlocal cleanup_task
            task = asyncio.current_task()
            assert task is not None
            cleanup_task = task
            cleanup_started.set()
            try:
                await allow_cleanup_finish.wait()
            except asyncio.CancelledError:
                await allow_cleanup_finish.wait()
                cleanup_finished.set()
                raise
            cleanup_finished.set()

        return (lambda *_args: _CompletedExecutor([])), cleanup

    driver = InProcessDurableDriver.lazy(
        runtime.async_session_factory,
        resource_factory=resource_factory,
    )
    await driver.start()
    close_task = asyncio.create_task(driver.aclose())
    try:
        await cleanup_started.wait()
        close_task.cancel()
        await asyncio.sleep(0)
        assert close_task.done() is False
        assert cleanup_finished.is_set() is False
        allow_cleanup_finish.set()
        with pytest.raises(asyncio.CancelledError):
            await close_task
        assert cleanup_finished.is_set()
        assert cleanup_task is close_task
        assert not any(task is cleanup_task and not task.done() for task in asyncio.all_tasks())
    finally:
        allow_cleanup_finish.set()
        if not close_task.done():
            with pytest.raises(asyncio.CancelledError):
                await close_task
        if not cleanup_finished.is_set():
            await asyncio.wait_for(cleanup_finished.wait(), timeout=1)
        await driver.aclose()
        await runtime.aclose()


@pytest.mark.asyncio
async def test_start_compensation_failure_is_retried_by_aclose_exactly_once(
    pg_test_container: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = DisposableEvalRuntime.provision(
        admin_dsn=_admin_dsn(pg_test_container),
        run_id=f"durable-start-compensation-{uuid4().hex}",
    )
    cleanup_calls = 0

    async def resource_factory() -> tuple[Any, Any]:
        async def cleanup() -> None:
            nonlocal cleanup_calls
            cleanup_calls += 1
            if cleanup_calls == 1:
                raise OSError("first resource cleanup failed")

        return (lambda *_args: _CompletedExecutor([])), cleanup

    driver = InProcessDurableDriver.lazy(
        runtime.async_session_factory,
        resource_factory=resource_factory,
    )
    original_mark_offline = driver._registry.mark_offline
    offline_calls = 0

    async def flaky_mark_offline(worker_id: UUID) -> None:
        nonlocal offline_calls
        offline_calls += 1
        if offline_calls == 1:
            raise OSError("first offline failed")
        await original_mark_offline(worker_id)

    monkeypatch.setattr(driver._registry, "mark_offline", flaky_mark_offline)

    def fail_worker_build(**_kwargs: Any) -> Any:
        raise RuntimeError("worker build failed")

    monkeypatch.setattr(durable_runtime_module, "RunChatWorker", fail_worker_build)
    try:
        with pytest.raises(RuntimeError, match="worker build failed"):
            await driver.start()
        worker_id = driver.worker_id
        assert offline_calls == 1
        assert cleanup_calls == 1
        async with runtime.async_session_factory() as session:
            worker_before_retry = await session.get(RunWorker, worker_id)
        assert worker_before_retry is not None
        assert worker_before_retry.status != "offline"

        await driver.aclose()
        async with runtime.async_session_factory() as session:
            worker_after_retry = await session.get(RunWorker, worker_id)
        assert worker_after_retry is not None
        assert worker_after_retry.status == "offline"
        assert offline_calls == 2
        assert cleanup_calls == 2

        await driver.aclose()
        assert offline_calls == 2
        assert cleanup_calls == 2
    finally:
        await driver.aclose()
        await runtime.aclose()


@pytest.mark.asyncio
async def test_start_compensation_cancellation_preempts_original_error_with_notes(
    pg_test_container: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = DisposableEvalRuntime.provision(
        admin_dsn=_admin_dsn(pg_test_container),
        run_id=f"durable-start-cancel-priority-{uuid4().hex}",
    )
    cleanup_calls = 0

    async def resource_factory() -> tuple[Any, Any]:
        async def cleanup() -> None:
            nonlocal cleanup_calls
            cleanup_calls += 1
            if cleanup_calls == 1:
                raise OSError("resource cleanup failed")

        return (lambda *_args: _CompletedExecutor([])), cleanup

    driver = InProcessDurableDriver.lazy(
        runtime.async_session_factory,
        resource_factory=resource_factory,
    )
    original_mark_offline = driver._registry.mark_offline
    offline_calls = 0

    async def cancelled_mark_offline(worker_id: UUID) -> None:
        nonlocal offline_calls
        offline_calls += 1
        if offline_calls == 1:
            raise asyncio.CancelledError("offline cleanup cancelled")
        await original_mark_offline(worker_id)

    monkeypatch.setattr(driver._registry, "mark_offline", cancelled_mark_offline)

    def fail_worker_build(**_kwargs: Any) -> Any:
        raise RuntimeError("worker build failed")

    monkeypatch.setattr(durable_runtime_module, "RunChatWorker", fail_worker_build)
    try:
        with pytest.raises(asyncio.CancelledError) as captured:
            await driver.start()
        notes = getattr(captured.value, "__notes__", [])
        assert any(
            "durable start failed: RuntimeError: worker build failed" in note for note in notes
        )
        assert any(
            "additional durable cleanup failure: OSError: resource cleanup failed" in note
            for note in notes
        )

        await driver.aclose()
        assert offline_calls == 2
        assert cleanup_calls == 2
    finally:
        await driver.aclose()
        await runtime.aclose()


@pytest.mark.asyncio
async def test_aclose_second_failure_cancellation_keeps_first_failure_note(
    pg_test_container: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = DisposableEvalRuntime.provision(
        admin_dsn=_admin_dsn(pg_test_container),
        run_id=f"durable-close-cancel-note-{uuid4().hex}",
    )
    cleanup_calls = 0

    async def resource_factory() -> tuple[Any, Any]:
        async def cleanup() -> None:
            nonlocal cleanup_calls
            cleanup_calls += 1
            if cleanup_calls == 1:
                raise asyncio.CancelledError("resource cleanup cancelled")

        return (lambda *_args: _CompletedExecutor([])), cleanup

    driver = InProcessDurableDriver.lazy(
        runtime.async_session_factory,
        resource_factory=resource_factory,
    )
    await driver.start()
    original_mark_offline = driver._registry.mark_offline
    offline_calls = 0

    async def failed_mark_offline(worker_id: UUID) -> None:
        nonlocal offline_calls
        offline_calls += 1
        if offline_calls == 1:
            raise OSError("offline cleanup failed")
        await original_mark_offline(worker_id)

    monkeypatch.setattr(driver._registry, "mark_offline", failed_mark_offline)
    try:
        with pytest.raises(asyncio.CancelledError) as captured:
            await driver.aclose()
        notes = getattr(captured.value, "__notes__", [])
        assert any(
            "additional durable cleanup failure: OSError: offline cleanup failed" in note
            for note in notes
        )

        await driver.aclose()
        assert offline_calls == 2
        assert cleanup_calls == 2
    finally:
        await driver.aclose()
        await runtime.aclose()


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
        assert observed.total_tokens == 10
        assert observed.cost_cny == pytest.approx(0.03)
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
