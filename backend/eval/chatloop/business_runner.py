"""Per-case orchestration for the versioned conversational business catalog."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

from eval.chatloop.case_schema import ConversationCase
from eval.chatloop.environment import EvalActor, TrialEnvironment
from eval.chatloop.faults import (
    DeterministicBarrier,
    FaultInjectingHub,
    FaultPlan,
    TransportFaultPlan,
)

TrialStatus = Literal["valid", "harness_failed", "invalid_evidence"]


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
                    if item.mode != "response_lost_after_commit"
                ),
                transport_fault=TransportFaultPlan(
                    response_lost_after_commit=any(
                        item.mode == "response_lost_after_commit" for item in case.fault_injection
                    )
                ),
                barrier=DeterministicBarrier(),
                random_seed=random_seed,
                execution_id=_execution_id(case.case_id, trial_index, random_seed),
            )
            observation = await self._executors[case.initial_state.execution_mode].execute(context)
        except asyncio.CancelledError as exc:
            cancellation = exc
        except Exception as exc:  # noqa: BLE001 - harness failures are trial facts
            failures.append(f"execution: {type(exc).__name__}: {exc}")

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


class DurableHttpBusinessExecutor:
    """Execute a durable case with its trial JWT against the real Run API."""

    def __init__(self, session_factory: Any, *, base_url: str, timeout_s: float = 60.0) -> None:
        self._session_factory = session_factory
        self._base_url = base_url
        self._timeout_s = timeout_s

    async def execute(self, context: BusinessExecutionContext) -> BusinessObservation:
        from eval.chatloop.sut_runner import DurableRunHttpTransport

        transport = DurableRunHttpTransport(
            self._session_factory,
            actor=context.actor,
            tenant_id=context.environment.tenant_id,
            base_url=self._base_url,
            timeout_s=self._timeout_s,
            batch_id=context.execution_id,
        )
        observed = await transport.execute_messages(
            case_id=context.case.case_id,
            messages=list(context.case.user_messages),
            run_idx=context.environment.trial_index,
            response_lost_after_commit=(context.transport_fault.response_lost_after_commit),
        )
        ledger = tuple(
            {
                "tool_name": call.get("tool_name", "unknown"),
                "arguments": dict(call.get("args") or {}),
                "result": {
                    "permission_decision": call.get("permission_decision"),
                    "permission_decisions": call.get("permission_decisions", []),
                },
                "error": None,
                "idempotency_key": call.get("tool_call_id"),
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
                "transport_fault": context.transport_fault.retry_policy,
            },
        )


class DirectToolLoopBusinessExecutor:
    """Run direct cases through the production ToolLoop and production tool wiring."""

    def __init__(
        self,
        session_factory: Any,
        *,
        sync_session_factory: Any,
        subprocess_env: dict[str, str],
        max_steps: int = 6,
    ) -> None:
        self._session_factory = session_factory
        self._sync_session_factory = sync_session_factory
        self._subprocess_env = dict(subprocess_env)
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
                # Memory-bearing cases fail capability preflight until run-scoped
                # Milvus exists. Never let ordinary direct cases initialize the
                # application's global PG/Milvus memory singleton.
                memory=object(),
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
            result: Any = None
            error: str | None = None
            if content is None:
                error = "missing tool response"
            elif isinstance(content, str) and content.startswith("[ERROR]"):
                error = content.removeprefix("[ERROR]").strip() or "unknown tool error"
            else:
                try:
                    result = json.loads(content) if isinstance(content, str) else content
                except json.JSONDecodeError:
                    error = "tool response is not valid JSON"
            row = {
                "tool_name": name,
                "arguments": arguments,
                "result": result,
                "error": error,
                "idempotency_key": call_id,
            }
            plan = next((item for item in fault_plans if item.target == name), None)
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
