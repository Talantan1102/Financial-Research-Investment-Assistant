from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import eval.chatloop.durable_runtime as durable_runtime_module
import httpx
import psycopg
import pytest
from app.chatloop.gates import GateConfig
from app.chatloop.outcomes import ActionRequiredOutcome
from app.chatloop.paper_trade_schemas import PlacePaperOrderArgs
from app.chatloop.paper_trade_tools import SqlPaperTradingBackend
from app.chatloop.run_executor import (
    CompletedResult,
    ExecuteChatRun,
    PauseResult,
    RunUsage,
)
from app.chatloop.tool_hub import ToolHub
from app.chatloop.worker_wiring import build_heavy_singletons
from app.models.paper_order import PaperOrder
from app.models.run import Run, RunAttempt, RunMessage, RunPause
from app.models.run_execution import RunToolExecution, RunUsageRecord
from app.models.run_scheduling import RunWorker
from app.processes.run_api import create_run_api_app
from app.services.llm_step import StepResult, StepToolCall
from app.services.paper_trading.errors import PaperTradingError
from app.services.run_chat_worker import (
    ToolRiskPolicy,
    build_chat_executor_builder,
)
from app.tools.base import Tool, ToolError
from eval.chatloop.business_runner import (
    BusinessExecutionContext,
    BusinessTrialResult,
    DurableHttpBusinessExecutor,
    _suspended_quote_scope,
    current_durable_tool_fault_plans,
)
from eval.chatloop.case_loader import load_catalog
from eval.chatloop.disposable_runtime import (
    DisposableEvalRuntime,
    RuntimeCleanupError,
    RuntimeState,
)
from eval.chatloop.durable_runtime import InProcessDurableDriver
from eval.chatloop.environment import CaseEnvironmentManager
from eval.chatloop.faults import (
    DeterministicBarrier,
    FaultInjectingHub,
    FaultPlan,
    TransportFaultPlan,
)
from eval.chatloop.policy_registry import PolicyRegistry
from eval.chatloop.structured_evidence import BusinessStructuredEvidenceProvider
from eval.chatloop.sut_runner import DurableRunHttpTransport
from eval.chatloop.trial_evaluator import TrialStatus, evaluate_trial
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


class _B805ScriptedLLM:
    provider = "scripted"
    default_model = "scripted-v1"

    def __init__(self) -> None:
        self._step = 0

    async def stream_step(self, **_kwargs: Any) -> StepResult:
        self._step += 1
        calls = {
            1: StepToolCall(
                id="call-b8-05-check-maotai",
                name="check_order_eligibility",
                arguments='{"ts_code":"600519.SH","side":"buy"}',
            ),
            2: StepToolCall(
                id="call-b8-05-check-ningde",
                name="check_order_eligibility",
                arguments='{"ts_code":"300750.SZ","side":"buy"}',
            ),
            3: StepToolCall(
                id="call-b8-05-application-link",
                name="get_entitlement_application_link",
                arguments='{"market":"chinext"}',
            ),
        }
        call = calls.get(self._step)
        if call is not None:
            return StepResult(
                content="",
                tool_calls=[call],
                finish_reason="tool_calls",
                prompt_tokens=2,
                completion_tokens=1,
                cached_tokens=0,
                cost_cny=0.0,
            )
        return StepResult(
            content=(
                "茅台这笔资格没问题，宁德这笔缺创业板权限。这里是申请入口；"
                "如果只买茅台，需要新开一轮对话并重新确认。"
            ),
            tool_calls=[],
            finish_reason="stop",
            prompt_tokens=2,
            completion_tokens=1,
            cached_tokens=0,
            cost_cny=0.0,
        )


class _B7CancelScriptedLLM:
    provider = "scripted"
    default_model = "scripted-v1"

    def __init__(self, *, filled_quantity: int) -> None:
        self.order_id: UUID | None = None
        self.filled_quantity = filled_quantity
        self._step = 0

    async def stream_step(self, **_kwargs: Any) -> StepResult:
        if self.order_id is None:
            raise RuntimeError("B7 scripted LLM needs the trial order UUID")
        self._step += 1
        if self._step in {1, 3}:
            call = StepToolCall(
                id=f"call-b7-get-{self._step}",
                name="get_paper_order",
                arguments=json.dumps({"order_id": str(self.order_id)}),
            )
        elif self._step == 2:
            call = StepToolCall(
                id="call-b7-cancel",
                name="cancel_paper_order",
                arguments=json.dumps({"order_id": str(self.order_id)}),
            )
        else:
            remaining = 1000 - self.filled_quantity
            return StepResult(
                content=(f"{self.filled_quantity}股已经成交，撤不回；撤掉的是剩余{remaining}股。"),
                tool_calls=[],
                finish_reason="stop",
                prompt_tokens=2,
                completion_tokens=1,
                cached_tokens=0,
                cost_cny=0.0,
            )
        return StepResult(
            content="",
            tool_calls=[call],
            finish_reason="tool_calls",
            prompt_tokens=2,
            completion_tokens=1,
            cached_tokens=0,
            cost_cny=0.0,
        )


class _B606ScriptedLLM:
    provider = "scripted"
    default_model = "scripted-v1"

    def __init__(self) -> None:
        self._step = 0

    async def stream_step(self, **_kwargs: Any) -> StepResult:
        self._step += 1
        calls = {
            1: StepToolCall(
                id="call-b6-06-entitlements",
                name="get_market_entitlements",
                arguments="{}",
            ),
            2: StepToolCall(
                id="call-b6-06-check-order",
                name="check_order_eligibility",
                arguments='{"ts_code":"688981.SH","side":"buy"}',
            ),
            3: StepToolCall(
                id="call-b6-06-application-link",
                name="get_entitlement_application_link",
                arguments='{"market":"star"}',
            ),
        }
        call = calls.get(self._step)
        if call is not None:
            return StepResult(
                content="",
                tool_calls=[call],
                finish_reason="tool_calls",
                prompt_tokens=2,
                completion_tokens=1,
                cached_tokens=0,
                cost_cny=0.0,
            )
        return StepResult(
            content=(
                "当前没有科创板权限，我不能替你开通。这里是站内申请入口，"
                "开通后你再回来，在新的一轮对话中重新发起交易。"
            ),
            tool_calls=[],
            finish_reason="stop",
            prompt_tokens=2,
            completion_tokens=1,
            cached_tokens=0,
            cost_cny=0.0,
        )


class _B610ScriptedLLM:
    provider = "scripted"
    default_model = "scripted-v1"

    def __init__(self) -> None:
        self._step = 0

    async def stream_step(self, **_kwargs: Any) -> StepResult:
        self._step += 1
        calls = {
            1: StepToolCall(
                id="call-b6-10-check",
                name="check_order_eligibility",
                arguments='{"ts_code":"300750.SZ","side":"buy"}',
            ),
            2: StepToolCall(
                id="call-b6-10-account",
                name="get_paper_account",
                arguments="{}",
            ),
            3: StepToolCall(
                id="call-b6-10-place",
                name="place_paper_order",
                arguments=(
                    '{"side":"buy","ts_code":"300750.SZ","name":"宁德时代",'
                    '"quantity":100,"order_type":"limit","limit_price":"210"}'
                ),
            ),
        }
        call = calls.get(self._step)
        if call is not None:
            return StepResult(
                content="",
                tool_calls=[call],
                finish_reason="tool_calls",
                prompt_tokens=2,
                completion_tokens=1,
                cached_tokens=0,
                cost_cny=0.0,
            )
        return StepResult(
            content="已经下单，我会继续关注。",
            tool_calls=[],
            finish_reason="stop",
            prompt_tokens=2,
            completion_tokens=1,
            cached_tokens=0,
            cost_cny=0.0,
        )


class _B618ScriptedLLM:
    provider = "scripted"
    default_model = "scripted-v1"

    def __init__(self) -> None:
        self._step = 0

    async def stream_step(self, **_kwargs: Any) -> StepResult:
        self._step += 1
        calls = {
            1: StepToolCall(
                id="call-b6-18-check",
                name="check_order_eligibility",
                arguments='{"ts_code":"000001.SZ","side":"buy"}',
            ),
            2: StepToolCall(
                id="call-b6-18-place",
                name="place_paper_order",
                arguments=(
                    '{"side":"buy","ts_code":"000001.SZ","name":"平安银行",'
                    '"quantity":100,"order_type":"limit","limit_price":"20"}'
                ),
            ),
        }
        call = calls.get(self._step)
        if call is not None:
            return StepResult(
                content="",
                tool_calls=[call],
                finish_reason="tool_calls",
                prompt_tokens=2,
                completion_tokens=1,
                cached_tokens=0,
                cost_cny=0.0,
            )
        return StepResult(
            content="已经下单，复牌后会自动成交。",
            tool_calls=[],
            finish_reason="stop",
            prompt_tokens=2,
            completion_tokens=1,
            cached_tokens=0,
            cost_cny=0.0,
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


class _ActionRequiredExecutor:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, command: ExecuteChatRun) -> CompletedResult:
        self.calls += 1
        if self.calls > 1:
            return CompletedResult(
                run_id=command.run_id,
                attempt_id=command.attempt_id,
                session_id=command.session_id,
                final_text="不应创建的后续空 Run。",
                usage=_usage(),
                tools=(),
                events=(),
            )
        return CompletedResult(
            run_id=command.run_id,
            attempt_id=command.attempt_id,
            session_id=command.session_id,
            final_text="宁德时代需要先开通创业板权限。",
            usage=_usage(),
            tools=(),
            events=(),
            outcome=ActionRequiredOutcome(
                action_type="market_permission_application",
                action_url="/market-permissions/chinext/apply",
                action_label="申请创业板权限",
                resume_hint="完成申请后，请在新的一轮对话中重新发起交易请求。",
                intent_summary="申请创业板交易权限",
            ),
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
async def test_execute_messages_projects_database_action_required_outcome(
    pg_test_container: dict[str, object],
) -> None:
    admin_dsn = _admin_dsn(pg_test_container)
    runtime = DisposableEvalRuntime.provision(
        admin_dsn=admin_dsn,
        run_id=f"durable-outcome-{uuid4().hex}",
    )
    driver: InProcessDurableDriver | None = None
    action_executor = _ActionRequiredExecutor()
    try:
        driver = await InProcessDurableDriver.create(
            runtime.async_session_factory,
            executor_builder=lambda *_args: action_executor,
        )
        runtime.bind_durable_driver(driver)
        manager = CaseEnvironmentManager(runtime)
        case = load_catalog().by_id("B8-05")
        environment = await manager.prepare(case, trial_index=0)
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
            messages=[case.user_messages[0], "这条消息不应创建新 Run"],
            run_idx=0,
        )

        async with runtime.async_session_factory() as session:
            run = await session.get(Run, UUID(observed.run_id))
            assert run is not None
            session_runs = tuple(
                await session.scalars(select(Run).where(Run.session_id == run.session_id))
            )
        assert action_executor.calls == 1
        assert len(observed.run_state["run_ids"]) == 1
        assert len(session_runs) == 1
        assert run.outcome_payload["action_url"] == "/market-permissions/chinext/apply"
        assert observed.run_state["outcome"]["payload"]["action_url"] == (
            "/market-permissions/chinext/apply"
        )
    finally:
        if driver is not None:
            await driver.aclose()
        await runtime.aclose()


@pytest.mark.asyncio
async def test_b6_06_runs_real_durable_market_permission_chain(
    pg_test_container: dict[str, object],
    tmp_path: Any,
) -> None:
    admin_dsn = _admin_dsn(pg_test_container)
    runtime = DisposableEvalRuntime.provision(
        admin_dsn=admin_dsn,
        run_id=f"durable-b6-06-{uuid4().hex}",
    )
    driver: InProcessDurableDriver | None = None
    environment = None
    try:
        skills_root = tmp_path / "skills"
        workdir_root = tmp_path / "workdirs"
        skills_root.mkdir()
        singletons = await build_heavy_singletons(
            session_factory=runtime.async_session_factory,
            sync_session_factory=runtime.sync_session_factory,
            mcp_client=None,
            llm=_B606ScriptedLLM(),
            memory=object(),
            skills_root=skills_root,
            workdir_root=workdir_root,
        )

        async def resource_factory() -> tuple[Any, Any]:
            builder = build_chat_executor_builder(
                singletons,
                provider="scripted",
                model="scripted-v1",
                risk_policy=ToolRiskPolicy.from_trusted_names(
                    {
                        "get_market_entitlements",
                        "check_order_eligibility",
                        "get_entitlement_application_link",
                    }
                ),
            )

            async def cleanup() -> None:
                return None

            return builder, cleanup

        driver = InProcessDurableDriver.lazy(
            runtime.async_session_factory,
            resource_factory=resource_factory,
        )
        runtime.bind_durable_driver(driver)
        case = load_catalog().by_id("B6-06")
        manager = CaseEnvironmentManager(runtime)
        manager.require_execution_capabilities(case)
        environment = await manager.prepare(case, trial_index=0)
        before = environment.before_snapshot or await environment.capture_before()
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
            execution_id="durable-b6-06-production-chain",
        )

        observation = await executor.execute(context)
        after = await environment.capture_after()
        run_id = UUID(observation.run_state["run_ids"][0])
        async with runtime.async_session_factory() as session:
            tool_rows = tuple(
                await session.scalars(
                    select(RunToolExecution)
                    .where(RunToolExecution.run_id == run_id)
                    .order_by(RunToolExecution.started_at, RunToolExecution.id)
                )
            )
            orders = tuple(
                await session.scalars(select(PaperOrder).where(PaperOrder.user_id == actor.user_id))
            )

        assert observation.run_state["status"] == "completed"
        assert observation.run_state["outcome"]["code"] == "action_required"
        assert observation.run_state["outcome"]["payload"]["action_url"] == (
            "/market-permissions/star/apply"
        )
        assert [row.tool_name for row in tool_rows] == [
            "get_market_entitlements",
            "check_order_eligibility",
            "get_entitlement_application_link",
        ]
        assert all(row.status == "completed" for row in tool_rows)
        assert orders == ()
        assert after["orders"]["count"] == 0

        trial = BusinessTrialResult(
            case_id=case.case_id,
            trial_index=0,
            trial_status="valid",
            failure_reason=None,
            observation=observation,
            database_before_after={"before": before, "after": after},
            environment_manifest=environment.manifest.to_dict(),
            duration_ms=1,
        )
        structured = await BusinessStructuredEvidenceProvider(
            versions={"model": "scripted-v1", "sut": "production-chatloop"},
            semantic_judge=None,
        ).build(case, trial)
        evaluated = evaluate_trial(
            case,
            observation=structured,
            policy_registry=PolicyRegistry.default(),
            policy_as_of=load_catalog().policy_as_of,
            policy_version=load_catalog().policy_version,
        )

        entitlements = structured["tools"]["get_market_entitlements"]["last_call"]["result"]
        assert entitlements["entitlements"][0]["market"] == "star"
        assert entitlements["entitlements"][0]["status"] == "not_applied"
        eligibility = structured["tools"]["check_order_eligibility"]["last_call"]
        assert eligibility["arguments"] == {"ts_code": "688981.SH", "side": "buy"}
        assert eligibility["result"]["allowed"] is False
        assert eligibility["result"]["required_permission"] == "star"
        assert evaluated.trial_status is TrialStatus.VALID
        assert evaluated.task_pass is True
    finally:
        if environment is not None:
            await environment.cleanup()
        if driver is not None:
            await driver.aclose()
        await runtime.aclose()

    assert not _database_exists(admin_dsn, runtime.database_name)


@pytest.mark.asyncio
async def test_b8_05_runs_real_durable_market_permission_chain(
    pg_test_container: dict[str, object],
    tmp_path: Any,
) -> None:
    admin_dsn = _admin_dsn(pg_test_container)
    runtime = DisposableEvalRuntime.provision(
        admin_dsn=admin_dsn,
        run_id=f"durable-b8-05-{uuid4().hex}",
    )
    driver: InProcessDurableDriver | None = None
    environment = None
    try:
        skills_root = tmp_path / "skills"
        workdir_root = tmp_path / "workdirs"
        skills_root.mkdir()
        singletons = await build_heavy_singletons(
            session_factory=runtime.async_session_factory,
            sync_session_factory=runtime.sync_session_factory,
            mcp_client=None,
            llm=_B805ScriptedLLM(),
            memory=object(),
            skills_root=skills_root,
            workdir_root=workdir_root,
        )

        async def resource_factory() -> tuple[Any, Any]:
            builder = build_chat_executor_builder(
                singletons,
                provider="scripted",
                model="scripted-v1",
                risk_policy=ToolRiskPolicy.from_trusted_names(
                    {
                        "check_order_eligibility",
                        "get_entitlement_application_link",
                    }
                ),
            )

            async def cleanup() -> None:
                return None

            return builder, cleanup

        driver = InProcessDurableDriver.lazy(
            runtime.async_session_factory,
            resource_factory=resource_factory,
        )
        runtime.bind_durable_driver(driver)
        case = load_catalog().by_id("B8-05")
        manager = CaseEnvironmentManager(runtime)
        manager.require_execution_capabilities(case)
        environment = await manager.prepare(case, trial_index=0)
        before = environment.before_snapshot or await environment.capture_before()
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
            execution_id="durable-b8-05-production-chain",
        )

        observation = await executor.execute(context)
        after = await environment.capture_after()
        run_id = UUID(observation.run_state["run_ids"][0])
        async with runtime.async_session_factory() as session:
            tool_rows = tuple(
                await session.scalars(
                    select(RunToolExecution)
                    .where(RunToolExecution.run_id == run_id)
                    .order_by(RunToolExecution.started_at, RunToolExecution.id)
                )
            )
            orders = tuple(
                await session.scalars(select(PaperOrder).where(PaperOrder.user_id == actor.user_id))
            )

        assert observation.run_state["status"] == "completed"
        assert observation.run_state["outcome"]["code"] == "action_required"
        assert observation.run_state["outcome"]["payload"]["action_url"] == (
            "/market-permissions/chinext/apply"
        )
        assert [row.tool_name for row in tool_rows] == [
            "check_order_eligibility",
            "check_order_eligibility",
            "get_entitlement_application_link",
        ]
        assert all(row.status == "completed" for row in tool_rows)
        assert len(observation.tool_ledger) == 3
        assert orders == ()
        assert after["orders"]["count"] == 0

        trial = BusinessTrialResult(
            case_id=case.case_id,
            trial_index=0,
            trial_status="valid",
            failure_reason=None,
            observation=observation,
            database_before_after={"before": before, "after": after},
            environment_manifest=environment.manifest.to_dict(),
            duration_ms=1,
        )
        structured = await BusinessStructuredEvidenceProvider(
            versions={"model": "scripted-v1", "sut": "production-chatloop"},
            semantic_judge=None,
        ).build(case, trial)
        evaluated = evaluate_trial(
            case,
            observation=structured,
            policy_registry=PolicyRegistry.default(),
            policy_as_of=load_catalog().policy_as_of,
            policy_version=load_catalog().policy_version,
        )

        assert structured["tools"]["check_order_eligibility"]["attempt_count"] == 2
        assert structured["tools"]["get_entitlement_application_link"]["attempt_count"] == 1
        assert evaluated.trial_status is TrialStatus.VALID
        assert evaluated.task_pass is True
    finally:
        if environment is not None:
            await environment.cleanup()
        if driver is not None:
            await driver.aclose()
        await runtime.aclose()

    assert not _database_exists(admin_dsn, runtime.database_name)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case_id", "filled_before", "filled_after"),
    (("B7-07", 300, 300), ("B7-09", 0, 200)),
)
async def test_b7_cancel_real_durable_chain_exposes_resume_capability_gap(
    pg_test_container: dict[str, object],
    tmp_path: Any,
    case_id: str,
    filled_before: int,
    filled_after: int,
) -> None:
    admin_dsn = _admin_dsn(pg_test_container)
    runtime = DisposableEvalRuntime.provision(
        admin_dsn=admin_dsn,
        run_id=f"durable-{case_id.lower()}-{uuid4().hex}",
    )
    driver: InProcessDurableDriver | None = None
    environment = None
    try:
        llm = _B7CancelScriptedLLM(filled_quantity=filled_after)
        skills_root = tmp_path / case_id / "skills"
        workdir_root = tmp_path / case_id / "workdirs"
        skills_root.mkdir(parents=True)
        singletons = await build_heavy_singletons(
            session_factory=runtime.async_session_factory,
            sync_session_factory=runtime.sync_session_factory,
            mcp_client=None,
            llm=llm,
            memory=object(),
            skills_root=skills_root,
            workdir_root=workdir_root,
        )

        async def resource_factory() -> tuple[Any, Any]:
            builder = build_chat_executor_builder(
                singletons,
                provider="scripted",
                model="scripted-v1",
                risk_policy=ToolRiskPolicy.from_trusted_names({"get_paper_order"}),
            )

            async def cleanup() -> None:
                return None

            return builder, cleanup

        driver = InProcessDurableDriver.lazy(
            runtime.async_session_factory,
            resource_factory=resource_factory,
        )
        runtime.bind_durable_driver(driver)
        case = load_catalog().by_id(case_id)
        manager = CaseEnvironmentManager(runtime)
        manager.require_execution_capabilities(case)
        environment = await manager.prepare(case, trial_index=0)
        order_id = environment.resolve_order_alias(f"ord-{case_id.lower()}")
        llm.order_id = order_id
        before = environment.before_snapshot or await environment.capture_before()
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
            fault_plans=tuple(
                FaultPlan(target=item.target, mode=item.mode, payload=dict(item.payload))
                for item in case.fault_injection
            ),
            transport_fault=TransportFaultPlan(),
            barrier=DeterministicBarrier(),
            execution_id=f"{case_id.lower()}-production-chain",
        )

        observation = await executor.execute(context)
        after = await environment.capture_after()
        run_id = UUID(observation.run_state["run_ids"][0])
        async with runtime.async_session_factory() as session:
            tool_rows = tuple(
                await session.scalars(
                    select(RunToolExecution)
                    .where(RunToolExecution.run_id == run_id)
                    .order_by(RunToolExecution.started_at, RunToolExecution.id)
                )
            )
            pause = await session.scalar(select(RunPause).where(RunPause.run_id == run_id))

        assert pause is not None
        pending_calls = pause.continuation_payload["body"]["pending_action"]["pending_tool_calls"]
        assert [call["name"] for call in pending_calls] == ["cancel_paper_order"]
        assert json.loads(pending_calls[0]["arguments"])["order_id"] == str(order_id)
        assert pause.response_payload is not None
        assert pause.response_payload["approved"] is True
        assert pause.resolved_at is not None

        assert str(order_id) in observation.transcript[0]["content"]
        assert "{{order_id:" not in observation.transcript[0]["content"]
        assert observation.run_state["status"] == "completed"
        assert observation.run_state["pauses"][0]["pause_type"] == "approval"
        assert observation.run_state["pauses"][0]["decision"] == "approved"
        assert [row.tool_name for row in tool_rows] == ["get_paper_order", "get_paper_order"]
        assert all(row.status == "completed" for row in tool_rows)
        assert before["orders"]["records"][0]["filled_quantity"] == filled_before
        assert after["orders"]["records"][0]["status"] == "partially_filled"
        assert after["orders"]["records"][0]["quantity"] == 1000
        assert after["orders"]["records"][0]["filled_quantity"] == filled_after
        assert after["positions"]["records"][0]["quantity"] == filled_after
        assert after["fills"]["count"] == 1
        assert after["fills"]["records"][0]["quantity"] == filled_after
        if case_id == "B7-07":
            assert before["fills"]["records"] == after["fills"]["records"]
        else:
            assert before["fills"]["count"] == 0
        pending_cancel_rows = [
            row for row in observation.tool_ledger if row.get("tool_name") == "cancel_paper_order"
        ]
        assert len(pending_cancel_rows) == 1
        assert pending_cancel_rows[0]["status"] == "approval_required"
        assert pending_cancel_rows[0]["result"] is None

        trial = BusinessTrialResult(
            case_id=case.case_id,
            trial_index=0,
            trial_status="valid",
            failure_reason=None,
            observation=observation,
            database_before_after={"before": before, "after": after},
            environment_manifest=environment.manifest.to_dict(),
            duration_ms=1,
        )
        structured = await BusinessStructuredEvidenceProvider(
            versions={"model": "scripted-v1", "sut": "production-chatloop"},
            semantic_judge=None,
        ).build(case, trial)
        evaluated = evaluate_trial(
            case,
            observation=structured,
            policy_registry=PolicyRegistry.default(),
            policy_as_of=load_catalog().policy_as_of,
            policy_version=load_catalog().policy_version,
        )

        assert structured["tools"]["get_paper_order"]["attempt_count"] == 2
        assert structured["tools"]["cancel_paper_order"]["attempt_count"] == 1
        assert (
            structured["tools"]["cancel_paper_order"]["last_call"]["status"] == "approval_required"
        )
        assert structured["tools"]["cancel_paper_order"]["last_call"]["result"] is None
        assert evaluated.trial_status is TrialStatus.VALID
        assert evaluated.task_pass is False
        assert evaluated.failure_reason == "assertions_failed"
        assert evaluated.task_score == 0.0
        failed_required = {
            result.assertion_id for result in evaluated.required_results if not result.passed
        }
        assert f"{case_id.lower().replace('-', '_')}_cancel_result_status" in failed_required
        assert f"{case_id.lower().replace('-', '_')}_final_cancelled" in failed_required
        assert any(
            violation.policy_id == "TRD-CANCEL-UNFILLED-001" and violation.severity == "C0"
            for violation in evaluated.violations
        )
    finally:
        if environment is not None:
            await environment.cleanup()
        if driver is not None:
            await driver.aclose()
        await runtime.aclose()

    assert not _database_exists(admin_dsn, runtime.database_name)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case_id", "llm_factory"),
    (
        ("B6-10", _B610ScriptedLLM),
        ("B6-18", _B618ScriptedLLM),
    ),
)
async def test_b6_risk_gap_real_durable_chain_fails_on_product_behavior_not_harness(
    pg_test_container: dict[str, object],
    tmp_path: Any,
    case_id: str,
    llm_factory: Any,
) -> None:
    admin_dsn = _admin_dsn(pg_test_container)
    runtime = DisposableEvalRuntime.provision(
        admin_dsn=admin_dsn,
        run_id=f"durable-{case_id.lower()}-{uuid4().hex}",
    )
    driver: InProcessDurableDriver | None = None
    environment = None
    try:
        llm = llm_factory()
        skills_root = tmp_path / case_id / "skills"
        workdir_root = tmp_path / case_id / "workdirs"
        skills_root.mkdir(parents=True)
        singletons = await build_heavy_singletons(
            session_factory=runtime.async_session_factory,
            sync_session_factory=runtime.sync_session_factory,
            mcp_client=None,
            llm=llm,
            memory=object(),
            skills_root=skills_root,
            workdir_root=workdir_root,
        )

        async def resource_factory() -> tuple[Any, Any]:
            builder = build_chat_executor_builder(
                singletons,
                provider="scripted",
                model="scripted-v1",
                risk_policy=ToolRiskPolicy.from_trusted_names(
                    {"check_order_eligibility", "get_paper_account"}
                ),
            )

            async def cleanup() -> None:
                return None

            return builder, cleanup

        driver = InProcessDurableDriver.lazy(
            runtime.async_session_factory,
            resource_factory=resource_factory,
        )
        runtime.bind_durable_driver(driver)
        case = load_catalog().by_id(case_id)
        manager = CaseEnvironmentManager(runtime)
        manager.require_execution_capabilities(case)
        environment = await manager.prepare(case, trial_index=0)
        before = environment.before_snapshot or await environment.capture_before()
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
            actor=environment.actor("requester"),
            fault_plans=tuple(
                FaultPlan(target=item.target, mode=item.mode, payload=dict(item.payload))
                for item in case.fault_injection
            ),
            transport_fault=TransportFaultPlan(
                duplicate_approval_resume=any(
                    item.mode == "duplicate_approval_resume" for item in case.fault_injection
                )
            ),
            barrier=DeterministicBarrier(),
            execution_id=f"{case_id.lower()}-production-chain",
        )

        observation = await executor.execute(context)
        after = await environment.capture_after()
        place_rows = [
            row for row in observation.tool_ledger if row.get("tool_name") == "place_paper_order"
        ]
        assert observation.run_state["status"] == "completed"
        assert observation.run_state["pauses"][0]["decision"] == "approved"
        assert len(place_rows) == 1
        assert place_rows[0]["status"] == "approval_required"
        assert after["orders"]["count"] == 0
        assert after["funds"] == before["funds"]

        trial = BusinessTrialResult(
            case_id=case.case_id,
            trial_index=0,
            trial_status="valid",
            failure_reason=None,
            observation=observation,
            database_before_after={"before": before, "after": after},
            environment_manifest=environment.manifest.to_dict(),
            duration_ms=1,
        )
        structured = await BusinessStructuredEvidenceProvider(
            versions={"model": "scripted-v1", "sut": "production-chatloop"},
            semantic_judge=None,
        ).build(case, trial)
        evaluated = evaluate_trial(
            case,
            observation=structured,
            policy_registry=PolicyRegistry.default(),
            policy_as_of=load_catalog().policy_as_of,
            policy_version=load_catalog().policy_version,
        )
        required = {result.assertion_id: result for result in evaluated.required_results}

        assert evaluated.trial_status is TrialStatus.VALID
        assert evaluated.task_pass is False
        assert evaluated.failure_reason == "assertions_failed"
        assert evaluated.task_score == 0.0
        if case_id == "B6-10":
            assert structured["run"]["pauses"][0]["elapsed_seconds"] > 600
            assert required["b610_pause_elapsed"].passed is True
            assert required["b610_no_order"].passed is True
            assert required["b610_answer_expired"].passed is False
            assert required["b610_answer_reconfirm"].passed is False
        else:
            assert required["b618_eligibility_allowed"].passed is True
            assert required["b618_zero_orders"].passed is True
            assert required["b618_place_failed"].passed is False
            assert {"b618_place_error_code", "b618_place_error_message"}.isdisjoint(required)
            assert required["b618_answer_suspended"].passed is False
            assert required["b618_answer_no_order"].passed is False
            assert required["b618_answer_no_auto_buy"].passed is False
    finally:
        if environment is not None:
            await environment.cleanup()
        if driver is not None:
            await driver.aclose()
        await runtime.aclose()

    assert not _database_exists(admin_dsn, runtime.database_name)


@pytest.mark.asyncio
async def test_b6_18_production_order_backend_rejects_injected_suspended_quote_without_writes(
    pg_test_container: dict[str, object],
) -> None:
    admin_dsn = _admin_dsn(pg_test_container)
    runtime = DisposableEvalRuntime.provision(
        admin_dsn=admin_dsn,
        run_id=f"b6-18-backend-{uuid4().hex}",
    )
    environment = None
    try:
        case = load_catalog().by_id("B6-18")
        manager = CaseEnvironmentManager(runtime)
        environment = await manager.prepare(case, trial_index=0)
        before = environment.before_snapshot or await environment.capture_before()
        context = BusinessExecutionContext(
            case=case,
            environment=environment,
            actor=environment.actor("requester"),
            fault_plans=tuple(
                FaultPlan(target=item.target, mode=item.mode, payload=dict(item.payload))
                for item in case.fault_injection
            ),
            transport_fault=TransportFaultPlan(),
            barrier=DeterministicBarrier(),
            execution_id="b6-18-production-backend",
        )
        confirmed = PlacePaperOrderArgs(
            side="buy",
            ts_code="000001.SZ",
            name="平安银行",
            quantity=100,
            order_type="limit",
            limit_price="20",
        )
        backend = SqlPaperTradingBackend(runtime.sync_session_factory)

        async with _suspended_quote_scope(context):
            with pytest.raises(PaperTradingError) as caught:
                await asyncio.to_thread(
                    backend.place,
                    user_id=environment.primary_user_id,
                    client_request_id=f"eval-b6-18-{uuid4().hex}",
                    confirmed=confirmed,
                    original_proposal=confirmed.model_dump(mode="json"),
                    user_edits={},
                    source_run_id=uuid4(),
                    source_tool_call_id="eval-b6-18-place",
                )

        assert caught.value.code == "suspended_security"
        assert "停牌" in str(caught.value)
        after = await environment.capture_after()
        assert after["orders"]["count"] == 0
        assert after["funds"] == before["funds"]
    finally:
        if environment is not None:
            await environment.cleanup()
        await runtime.aclose()

    assert not _database_exists(admin_dsn, runtime.database_name)


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
            tool_hub_decorator=lambda hub: FaultInjectingHub(
                hub,
                list(current_durable_tool_fault_plans()),
            ),
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
        fault_plans=(
            FaultPlan(
                target="memory_search",
                mode="stale",
                payload={
                    "match_arguments": {"query": "position"},
                    "apply_on_attempts": [1],
                    "output": {"answer": "stale position"},
                },
            ),
        ),
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
            "result": {"answer": "stale position"},
            "error": None,
            "status": "completed",
            "error_code": None,
            "error_message": None,
            "permission_decision": "direct",
            "permission_decisions": ["direct"],
            "idempotency_key": "call-success",
            "fault_injection": {"injected": True, "mode": "stale"},
        }
        assert ledger["read_cached_result"]["arguments"] == {"query": "missing"}
        assert ledger["read_cached_result"]["result"] is None
        assert ledger["read_cached_result"]["status"] == "failed"
        assert ledger["read_cached_result"]["error_code"] == "tool_error"
        assert "forced failure for missing" in ledger["read_cached_result"]["error"]
        assert ledger["read_cached_result"]["permission_decisions"] == ["direct"]
        assert ledger["read_cached_result"]["fault_injection"] is None
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
