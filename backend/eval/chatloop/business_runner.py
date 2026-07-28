"""Per-case orchestration for the versioned conversational business catalog."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol
from uuid import UUID

from eval.chatloop.case_schema import (
    ConversationCase,
    validate_approval_delay_fault,
    validate_approval_pause_fault,
    validate_order_alias,
    validate_suspended_quote_fault,
)
from eval.chatloop.environment import EvalActor, TrialEnvironment
from eval.chatloop.faults import (
    DeterministicBarrier,
    FaultInjectingHub,
    FaultPlan,
    TransportFaultPlan,
)

TrialStatus = Literal["valid", "harness_failed", "invalid_evidence"]

_DURABLE_TOOL_FAULT_PLANS: ContextVar[tuple[FaultPlan, ...]] = ContextVar(
    "chatloop_eval_durable_tool_fault_plans",
    default=(),
)


def current_durable_tool_fault_plans() -> tuple[FaultPlan, ...]:
    """Return evaluator-owned tool faults active for the current durable attempt."""

    return tuple(
        plan
        for plan in _DURABLE_TOOL_FAULT_PLANS.get()
        if plan.mode not in {"approval_pause", "approval_delay", "suspended_quote"}
    )


@dataclass(slots=True)
class BusinessExecutionContext:
    """Trial-scoped dependencies visible to an execution adapter, never the Agent."""

    case: ConversationCase
    environment: TrialEnvironment
    actor: EvalActor
    fault_plans: tuple[FaultPlan, ...]
    transport_fault: TransportFaultPlan
    barrier: DeterministicBarrier
    random_seed: int = 0
    execution_id: str = ""
    timeline: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class BusinessObservation:
    """Complete raw observation returned by a direct or durable executor."""

    transcript: tuple[dict[str, Any], ...]
    tool_ledger: tuple[dict[str, Any], ...]
    run_state: dict[str, Any]
    evidence: dict[str, Any] = field(default_factory=dict)
    cost_cny: float | None = None
    total_tokens: int | None = None


class BusinessCaseExecutor(Protocol):
    async def execute(self, context: BusinessExecutionContext) -> BusinessObservation: ...


@dataclass(frozen=True, slots=True)
class BusinessTrialResult:
    case_id: str
    trial_index: int
    trial_status: TrialStatus
    failure_reason: str | None
    observation: BusinessObservation | None
    database_before_after: dict[str, Any]
    environment_manifest: dict[str, Any]
    duration_ms: int


class BusinessRunner:
    """Create, execute, capture, and clean exactly one isolated business trial."""

    def __init__(
        self,
        environment_manager: Any,
        *,
        direct_executor: BusinessCaseExecutor,
        durable_executor: BusinessCaseExecutor,
    ) -> None:
        self._environment_manager = environment_manager
        self._executors = {
            "direct": direct_executor,
            "durable": durable_executor,
        }

    async def run_trial(
        self,
        case: ConversationCase,
        *,
        trial_index: int,
        random_seed: int = 0,
    ) -> BusinessTrialResult:
        started = time.perf_counter()
        self._environment_manager.require_execution_capabilities(case)
        environment = await self._environment_manager.prepare(case, trial_index=trial_index)
        observation: BusinessObservation | None = None
        failures: list[str] = []
        after: dict[str, Any] = {}
        cancellation: asyncio.CancelledError | None = None

        try:
            actor = environment.actor("requester")
            if case.initial_state.execution_mode == "durable" and not actor.is_authenticated:
                raise RuntimeError("durable business execution requires an authenticated requester")
            context = BusinessExecutionContext(
                case=case,
                environment=environment,
                actor=actor,
                fault_plans=tuple(
                    FaultPlan(target=item.target, mode=item.mode, payload=dict(item.payload))
                    for item in case.fault_injection
                    if item.mode
                    not in {
                        "response_lost_after_commit",
                        "duplicate_approval_resume",
                    }
                    or (
                        item.mode == "response_lost_after_commit"
                        and case.initial_state.execution_mode == "direct"
                    )
                ),
                transport_fault=TransportFaultPlan(
                    duplicate_approval_resume=(
                        case.initial_state.execution_mode == "durable"
                        and any(
                            item.mode == "duplicate_approval_resume"
                            for item in case.fault_injection
                        )
                    ),
                ),
                barrier=DeterministicBarrier(),
                random_seed=random_seed,
                execution_id=_execution_id(case.case_id, trial_index, random_seed),
            )
            observation = await self._executors[case.initial_state.execution_mode].execute(context)
        except asyncio.CancelledError as exc:
            cancellation = exc
        except Exception as exc:  # noqa: BLE001 - harness failures are trial facts
            failures.append(f"execution: {_format_exception(exc)}")

        if cancellation is None:
            try:
                after = await environment.capture_after()
            except Exception as exc:  # noqa: BLE001
                failures.append(f"capture: {type(exc).__name__}: {exc}")

        manifest = environment.manifest.to_dict()
        try:
            await asyncio.shield(environment.cleanup())
        except Exception as exc:  # noqa: BLE001
            failures.append(f"cleanup: {type(exc).__name__}: {exc}")
        if cancellation is not None:
            raise cancellation

        return BusinessTrialResult(
            case_id=case.case_id,
            trial_index=trial_index,
            trial_status="harness_failed" if failures else "valid",
            failure_reason="; ".join(failures) or None,
            observation=observation if not failures else None,
            database_before_after={
                "before": environment.before_snapshot or {},
                "after": after,
            },
            environment_manifest=manifest,
            duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
        )


def _format_exception(error: BaseException) -> str:
    """Keep nested TaskGroup causes visible in persisted harness evidence."""

    rendered = f"{type(error).__name__}: {error}"
    if isinstance(error, BaseExceptionGroup):
        children = "; ".join(_format_exception(child) for child in error.exceptions)
        return f"{rendered} [{children}]"
    return rendered


class DurableHttpBusinessExecutor:
    """Execute a durable case with its trial JWT against the real Run API."""

    def __init__(
        self,
        session_factory: Any,
        *,
        base_url: str,
        timeout_s: float = 60.0,
        client_transport: Any | None = None,
        progress_callback: Callable[[], Awaitable[Any]] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._base_url = base_url
        self._timeout_s = timeout_s
        self._client_transport = client_transport
        self._progress_callback = progress_callback

    async def execute(self, context: BusinessExecutionContext) -> BusinessObservation:
        from eval.chatloop.sut_runner import DurableRunHttpTransport

        pause_callback = _approval_pause_callback(context)

        transport = DurableRunHttpTransport(
            self._session_factory,
            actor=context.actor,
            tenant_id=context.environment.tenant_id,
            base_url=self._base_url,
            timeout_s=self._timeout_s,
            batch_id=context.execution_id,
            client_transport=self._client_transport,
            progress_callback=self._progress_callback,
            approval_pause_callback=pause_callback,
        )
        fault_token = _DURABLE_TOOL_FAULT_PLANS.set(context.fault_plans)
        try:
            async with _suspended_quote_scope(context):
                observed = await transport.execute_messages(
                    case_id=context.case.case_id,
                    messages=_render_environment_messages(
                        context.case.user_messages,
                        context.environment.manifest.order_aliases,
                        order_alias_owners=context.environment.manifest.order_alias_owners,
                        requester_user_id=context.actor.user_id,
                    ),
                    run_idx=context.environment.trial_index,
                    duplicate_approval_resume=(context.transport_fault.duplicate_approval_resume),
                )
        finally:
            _DURABLE_TOOL_FAULT_PLANS.reset(fault_token)
        ledger = tuple(
            {
                "tool_name": call.get("tool_name", "unknown"),
                "arguments": dict(call.get("args") or {}),
                "result": call.get("result") if call.get("status") == "completed" else None,
                "error": call.get("error"),
                "status": call.get("status"),
                "error_code": call.get("error_code"),
                "error_message": call.get("error_message"),
                "permission_decision": call.get("permission_decision"),
                "permission_decisions": call.get("permission_decisions", []),
                "idempotency_key": call.get("tool_call_id"),
                "fault_injection": _durable_fault_provenance(
                    call.get("result_summary"),
                    call.get("error_code"),
                ),
            }
            for call in observed.tool_calls
        )
        transcript = tuple(observed.run_state.get("transcript", []))
        return BusinessObservation(
            transcript=transcript,
            tool_ledger=ledger,
            run_state=observed.run_state,
            evidence={
                "response_text": observed.response_text,
                "execution_path": "durable",
                "run_id": observed.run_id,
                "transport_fault": context.transport_fault.retry_policy,
            },
            cost_cny=observed.cost_cny,
            total_tokens=observed.total_tokens,
        )


def _durable_fault_provenance(
    result_summary: Any,
    error_code: Any,
) -> dict[str, Any] | None:
    if isinstance(result_summary, dict):
        data = result_summary.get("tool_call_data")
        if isinstance(data, dict) and data.get("fault_injected") is True:
            mode = data.get("fault_mode")
            if isinstance(mode, str) and mode:
                return {"injected": True, "mode": mode}
    if error_code in {"timeout", "error", "response_lost_after_commit"}:
        return {"injected": True, "mode": error_code}
    return None


_ORDER_ID_PLACEHOLDER = re.compile(r"\{\{order_id:([A-Za-z0-9][A-Za-z0-9._-]{0,63})\}\}")


def _render_environment_messages(
    messages: list[str],
    order_aliases: dict[str, str],
    *,
    order_alias_owners: dict[str, str],
    requester_user_id: UUID | None,
) -> list[str]:
    """Replace catalog aliases only after the isolated order rows exist."""

    def replace(match: re.Match[str]) -> str:
        alias = validate_order_alias(match.group(1))
        try:
            raw_order_id = order_aliases[alias]
        except KeyError as exc:
            raise KeyError(f"unknown order placeholder alias {alias!r}") from exc
        try:
            raw_owner = order_alias_owners[alias]
        except KeyError as exc:
            raise ValueError(f"order alias {alias!r} is missing owner") from exc
        if requester_user_id is None:
            raise PermissionError(f"order alias {alias!r} has no authenticated requester")
        try:
            owner_user_id = UUID(raw_owner)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"order alias {alias!r} has invalid owner UUID") from exc
        if owner_user_id != requester_user_id:
            raise PermissionError(f"order alias {alias!r} does not belong to requester")
        try:
            return str(UUID(raw_order_id))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid UUID for order alias {alias!r}") from exc

    rendered = [_ORDER_ID_PLACEHOLDER.sub(replace, message) for message in messages]
    if any("{{order_id" in message for message in rendered):
        raise ValueError("malformed order placeholder")
    return rendered


def _approval_pause_callback(
    context: BusinessExecutionContext,
) -> Callable[[str, Any], Awaitable[None]] | None:
    plans = [plan for plan in context.fault_plans if plan.mode == "approval_pause"]
    delay_plans = [plan for plan in context.fault_plans if plan.mode == "approval_delay"]
    if not plans and not delay_plans:
        return None
    if context.case.initial_state.execution_mode != "durable":
        mode = "approval_pause" if plans else "approval_delay"
        raise ValueError(f"{mode} requires execution_mode=durable")
    if plans and len(plans) != 1:
        raise ValueError("durable eval supports at most one approval_pause plan")
    if len(delay_plans) > 1:
        raise ValueError("durable eval supports at most one approval_delay plan")
    callbacks: list[Callable[[str, Any], Awaitable[None]]] = []

    if plans:
        plan = plans[0]
        alias, quantity = validate_approval_pause_fault(plan.target, plan.payload)
        callbacks.append(_settlement_pause_callback(context, alias=alias, quantity=quantity))
    if delay_plans:
        plan = delay_plans[0]
        elapsed_seconds = validate_approval_delay_fault(plan.target, plan.payload)
        callbacks.append(_approval_delay_apply_callback(context, elapsed_seconds=elapsed_seconds))

    async def apply(run_id: str, pause: Any) -> None:
        for callback in callbacks:
            await callback(run_id, pause)

    return apply


def _settlement_pause_callback(
    context: BusinessExecutionContext,
    *,
    alias: str,
    quantity: int,
) -> Callable[[str, Any], Awaitable[None]]:
    requester_user_id = context.actor.user_id
    if requester_user_id is None:
        raise PermissionError("approval_pause requires an authenticated requester")
    try:
        raw_owner_user_id = context.environment.manifest.order_alias_owners[alias]
    except KeyError as exc:
        raise ValueError(f"order alias {alias!r} is missing owner") from exc
    try:
        expected_user_id = UUID(raw_owner_user_id)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"order alias {alias!r} has invalid owner UUID") from exc
    if expected_user_id != requester_user_id:
        raise PermissionError(f"order alias {alias!r} does not belong to approval requester")
    expected_order_id = context.environment.resolve_order_alias(alias)
    applied = False

    async def apply(_run_id: str, pause: Any) -> None:
        nonlocal applied
        if applied:
            raise RuntimeError("approval-pause settlement hook was invoked more than once")
        paused_calls = pause.request_payload.get("tool_calls", [])
        cancel_calls = [
            call
            for call in paused_calls
            if isinstance(call, dict) and call.get("name") == "cancel_paper_order"
        ]
        if len(cancel_calls) != 1:
            raise RuntimeError("settlement hook requires exactly one paused cancel_paper_order")
        arguments = cancel_calls[0].get("arguments", {})
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        if str(arguments.get("order_id")) != str(expected_order_id):
            raise RuntimeError("paused cancel_paper_order does not target the seeded order")
        await context.environment.apply_order_fill(
            order_alias=alias,
            quantity=quantity,
            expected_user_id=expected_user_id,
            requester_user_id=requester_user_id,
        )
        applied = True

    return apply


def _approval_delay_apply_callback(
    context: BusinessExecutionContext,
    *,
    elapsed_seconds: int,
) -> Callable[[str, Any], Awaitable[None]]:
    requester_user_id = context.actor.user_id
    if requester_user_id is None:
        raise PermissionError("approval_delay requires an authenticated requester")
    applied = False

    async def apply(run_id: str, pause: Any) -> None:
        nonlocal applied
        if applied:
            raise RuntimeError("approval-delay hook was invoked more than once")
        if pause.pause_type != "approval":
            raise RuntimeError("approval_delay requires an approval pause")
        if UUID(str(run_id)) != UUID(str(pause.run_id)):
            raise RuntimeError("approval_delay pause does not belong to the observed Run")
        paused_calls = pause.request_payload.get("tool_calls", [])
        place_calls = [
            call
            for call in paused_calls
            if isinstance(call, dict) and call.get("name") == "place_paper_order"
        ]
        if len(place_calls) != 1:
            raise RuntimeError("approval_delay requires exactly one paused place_paper_order")
        await context.environment.apply_approval_delay(
            run_id=UUID(str(run_id)),
            pause_id=UUID(str(pause.id)),
            elapsed_seconds=elapsed_seconds,
            requester_user_id=requester_user_id,
        )
        applied = True

    return apply


_SUSPENDED_QUOTE_LOCK = asyncio.Lock()


@asynccontextmanager
async def _suspended_quote_scope(context: BusinessExecutionContext):
    plans = [plan for plan in context.fault_plans if plan.mode == "suspended_quote"]
    if not plans:
        yield
        return
    if context.case.initial_state.execution_mode != "durable":
        raise ValueError("suspended_quote requires execution_mode=durable")
    if len(plans) != 1:
        raise ValueError("durable eval supports at most one suspended_quote plan")
    ts_code = validate_suspended_quote_fault(plans[0].target, plans[0].payload)

    from datetime import datetime
    from zoneinfo import ZoneInfo

    import pandas as pd
    from app.services.paper_trading.quote_provider import TushareRealtimeQuoteProvider

    now = datetime.now(ZoneInfo("Asia/Shanghai"))

    def suspended_fetch(requested_ts_code: str) -> Any:
        if requested_ts_code != ts_code:
            raise RuntimeError("eval suspended quote requested an unexpected security")
        row: dict[str, object] = {
            "TS_CODE": ts_code,
            "NAME": "评估停牌证券",
            "DATE": now.strftime("%Y%m%d"),
            "TIME": now.strftime("%H:%M:%S"),
            "PRE_CLOSE": "11.20",
            "PRICE": "0",
        }
        for level in range(1, 6):
            row.update(
                {
                    f"B{level}_P": "0",
                    f"B{level}_V": "0",
                    f"A{level}_P": "0",
                    f"A{level}_V": "0",
                }
            )
        return pd.DataFrame([row])

    async with _SUSPENDED_QUOTE_LOCK:
        provider_class: Any = TushareRealtimeQuoteProvider
        original = inspect.getattr_static(provider_class, "_sdk_fetch")
        provider_class._sdk_fetch = staticmethod(suspended_fetch)
        try:
            yield
        finally:
            provider_class._sdk_fetch = original


class DirectToolLoopBusinessExecutor:
    """Run direct cases through the production ToolLoop and production tool wiring."""

    def __init__(
        self,
        session_factory: Any,
        *,
        sync_session_factory: Any,
        subprocess_env: dict[str, str],
        memory: Any,
        max_steps: int = 6,
    ) -> None:
        self._session_factory = session_factory
        self._sync_session_factory = sync_session_factory
        self._subprocess_env = dict(subprocess_env)
        self._memory = memory
        self._max_steps = max_steps

    async def execute(self, context: BusinessExecutionContext) -> BusinessObservation:
        from app.chatloop.context import ContextDeps
        from app.chatloop.eval_agent import ChatLoopAgent
        from app.chatloop.events import SeqCounter
        from app.chatloop.gates import GateConfig
        from app.chatloop.loop import ToolLoop
        from app.chatloop.state import ChatLoopState
        from app.chatloop.worker_wiring import build_heavy_singletons, build_turn_components
        from app.services.mcp_client import MCPClient

        transcript: list[dict[str, Any]] = []
        ledger: list[dict[str, Any]] = []
        conversation: list[dict[str, Any]] = []
        total_cost = 0.0
        total_tokens = 0
        seen_tool_call_ids: set[str] = set()

        async def emit(event: Any) -> None:
            context.timeline.append(
                {
                    "event": str(event.type),
                    "seq": int(event.seq),
                    "step": int(event.step),
                }
            )

        async with MCPClient.from_subprocess(
            profile="chat_tools",
            env_overrides=self._subprocess_env,
        ) as mcp_client:
            singletons = await build_heavy_singletons(
                session_factory=self._session_factory,
                sync_session_factory=self._sync_session_factory,
                mcp_client=mcp_client,
                memory=self._memory,
            )
            for turn_index, message in enumerate(context.case.user_messages):
                transcript.append({"role": "user", "content": message})
                conversation.append({"role": "user", "content": message})
                components = build_turn_components(
                    singletons,
                    emit=emit,
                    seq_counter=SeqCounter(),
                )
                faulted_hub = FaultInjectingHub(
                    components.tool_hub,
                    list(context.fault_plans),
                )
                hub = _AllowedToolsHub(faulted_hub, frozenset(context.case.available_tools))
                state = ChatLoopState(
                    user_id=(
                        str(context.actor.user_id)
                        if context.actor.user_id is not None
                        else f"anonymous:{context.case.case_id}:{turn_index}"
                    ),
                    session_id=f"eval:{context.execution_id}",
                    request_id=(f"eval:{context.execution_id}:{turn_index}"),
                    messages=list(conversation),
                )
                loop = ToolLoop(
                    llm=components.llm,
                    tool_hub=hub,
                    context_deps=ContextDeps(
                        system_prompt=components.system_prompt,
                        skill_listing=components.skill_listing,
                    ),
                    gate_cfg=GateConfig(max_steps=self._max_steps),
                    emit=emit,
                )
                final = await loop.run(state)
                response = final.final_response or ChatLoopAgent._last_assistant_content(final)
                transcript.append({"role": "assistant", "content": response})
                conversation = list(final.messages)
                total_cost += final.budget_spent_cny
                total_tokens += final.budget_spent_tokens
                for call in extract_business_tool_ledger(
                    final,
                    fault_plans=context.fault_plans,
                ):
                    call_id = str(call["idempotency_key"])
                    if call_id in seen_tool_call_ids:
                        continue
                    seen_tool_call_ids.add(call_id)
                    ledger.append(call)
                if _user_aborted(message) or _is_terminal_answer(response):
                    break

        return BusinessObservation(
            transcript=tuple(transcript),
            tool_ledger=tuple(ledger),
            run_state={"status": "completed", "timeline": list(context.timeline)},
            evidence={"execution_path": "direct"},
            cost_cny=total_cost,
            total_tokens=total_tokens,
        )


class _AllowedToolsHub:
    """Expose only catalog-declared tools plus production control tools."""

    _CONTROL_TOOLS = frozenset({"search_tools", "ask_user"})

    def __init__(self, inner: Any, allowed: frozenset[str]) -> None:
        self._inner = inner
        self._allowed = allowed | self._CONTROL_TOOLS

    def schemas_for_llm(self) -> list[dict[str, Any]]:
        return [
            schema
            for schema in self._inner.schemas_for_llm()
            if schema.get("function", {}).get("name") in self._allowed
        ]

    async def dispatch(self, calls: list[Any], state: Any) -> list[Any]:
        forbidden = [call.name for call in calls if call.name not in self._allowed]
        if forbidden:
            raise RuntimeError(f"Agent called tools outside case scope: {sorted(forbidden)}")
        return await self._inner.dispatch(calls, state)


def _user_aborted(message: str) -> bool:
    normalized = "".join(message.lower().split())
    return any(token in normalized for token in ("取消", "算了", "不弄了", "终止", "停止"))


def _is_terminal_answer(answer: str) -> bool:
    lowered = answer.lower()
    return "action_required" in lowered or "需要您先完成" in answer


def observation_as_evidence(observation: BusinessObservation) -> dict[str, Any]:
    """Project an observation into JSON-compatible artifact sections."""
    return asdict(observation)


def extract_business_tool_ledger(
    state: Any,
    *,
    fault_plans: tuple[FaultPlan, ...] = (),
) -> tuple[dict[str, Any], ...]:
    """Join assistant tool requests to tool responses without losing raw facts."""
    responses = {
        str(message.get("tool_call_id")): message.get("content")
        for message in state.messages
        if message.get("role") == "tool" and message.get("tool_call_id")
    }
    rows: list[dict[str, Any]] = []
    fault_attempts = [0 for _plan in fault_plans]
    for message in state.messages:
        if message.get("role") != "assistant":
            continue
        for raw_call in message.get("tool_calls", []) or []:
            call_id = str(raw_call.get("id") or "")
            function = raw_call.get("function") or {}
            name = str(function.get("name") or "")
            if not call_id or not name:
                continue
            try:
                arguments = json.loads(function.get("arguments") or "{}")
                if not isinstance(arguments, dict):
                    arguments = {}
            except (TypeError, ValueError, json.JSONDecodeError):
                arguments = {}
            content = responses.get(call_id)
            plan: FaultPlan | None = None
            for plan_index, candidate in enumerate(fault_plans):
                if candidate.target != name:
                    continue
                expected_arguments = candidate.payload.get("match_arguments", {})
                if not isinstance(expected_arguments, dict) or not all(
                    arguments.get(key) == value for key, value in expected_arguments.items()
                ):
                    continue
                fault_attempts[plan_index] += 1
                selected_attempts = candidate.payload.get("apply_on_attempts")
                if selected_attempts is None or fault_attempts[plan_index] in selected_attempts:
                    plan = candidate
                    break
            result: Any = None
            error: str | None = None
            status: str | None = None
            error_code: str | None = None
            error_message: str | None = None
            if content is None:
                error = "missing tool response"
            elif not isinstance(content, str):
                error = "tool response has invalid structure"
            elif content.startswith("[ERROR]"):
                error = content.removeprefix("[ERROR]").strip() or "unknown tool error"
                status = "failed"
                error_code = "tool_error"
                encoded_fault = re.match(r"^\[([a-z_]+)\](?:\s|$)", error)
                if (
                    plan is not None
                    and encoded_fault is not None
                    and encoded_fault.group(1) == plan.mode
                ):
                    error_code = encoded_fault.group(1)
                error_message = error
            else:
                try:
                    result = json.loads(content)
                except json.JSONDecodeError:
                    error = "tool response is not valid JSON"
                else:
                    status = "completed"
            row = {
                "tool_name": name,
                "arguments": arguments,
                "result": result,
                "error": error,
                "idempotency_key": call_id,
            }
            if status is not None:
                row.update(
                    {
                        "status": status,
                        "error_code": error_code,
                        "error_message": error_message,
                    }
                )
            if plan is not None:
                row["fault_injection"] = {
                    "injected": True,
                    "mode": plan.mode,
                    "target": plan.target,
                }
            rows.append(row)
    return tuple(rows)


def _execution_id(case_id: str, trial_index: int, random_seed: int) -> str:
    """Derive stable harness request identity; this does not seed the model provider."""
    payload = f"{case_id}:{trial_index}:{random_seed}".encode()
    return hashlib.sha256(payload).hexdigest()[:24]


__all__ = [
    "BusinessCaseExecutor",
    "BusinessExecutionContext",
    "BusinessObservation",
    "BusinessRunner",
    "BusinessTrialResult",
    "DirectToolLoopBusinessExecutor",
    "DurableHttpBusinessExecutor",
    "TrialStatus",
    "extract_business_tool_ledger",
    "observation_as_evidence",
]
