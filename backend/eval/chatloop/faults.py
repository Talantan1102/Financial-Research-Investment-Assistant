"""Evaluation-only fault decorators for real conversational execution paths."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from app.agents.schemas import ToolResult
from app.chatloop.state import ChatLoopState
from app.services.llm_step import StepToolCall

FaultMode = Literal["timeout", "error", "stale", "conflict"]


class ToolHubLike(Protocol):
    def schemas_for_llm(self) -> list[dict[str, Any]]: ...

    async def dispatch(
        self,
        calls: list[StepToolCall],
        state: ChatLoopState,
    ) -> list[ToolResult]: ...


@dataclass(frozen=True, slots=True)
class FaultPlan:
    """One deterministic fault attached to a production tool name."""

    target: str
    mode: FaultMode
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.target.strip():
            raise ValueError("fault target must be non-empty")


@dataclass(frozen=True, slots=True)
class TransportFaultPlan:
    """Faults around durable HTTP actions, never inside production services."""

    response_lost_after_commit: bool = False

    @property
    def retry_policy(self) -> Literal["normal", "observe_before_retry"]:
        return "observe_before_retry" if self.response_lost_after_commit else "normal"


class FaultToolResult(ToolResult):
    """A normal ToolResult with an evaluator-readable deterministic error code."""

    error_code: str


class FaultInjectingHub:
    """Decorate a real ToolHub without exposing fault controls to the Agent."""

    def __init__(self, inner: ToolHubLike, plans: list[FaultPlan]) -> None:
        self._inner = inner
        self._plans = tuple(plans)
        known_targets = {
            str(function.get("name"))
            for schema in inner.schemas_for_llm()
            if isinstance(schema, dict)
            and isinstance((function := schema.get("function")), dict)
            and function.get("name")
        }
        unsupported = sorted({plan.target for plan in self._plans} - known_targets)
        if unsupported:
            raise ValueError(f"unsupported fault target(s): {unsupported}")
        scenario_specific = sorted({plan.mode for plan in self._plans if plan.mode == "conflict"})
        if scenario_specific:
            raise ValueError(
                f"scenario-specific fault mode requires a dedicated hook: {scenario_specific}"
            )

    def schemas_for_llm(self) -> list[dict[str, Any]]:
        return self._inner.schemas_for_llm()

    async def dispatch(
        self,
        calls: list[StepToolCall],
        state: ChatLoopState,
    ) -> list[ToolResult]:
        if not calls:
            return []

        results: list[ToolResult | None] = [None] * len(calls)
        forwarded: list[StepToolCall] = []
        forwarded_indices: list[int] = []
        plans_by_index: dict[int, FaultPlan] = {}

        for index, call in enumerate(calls):
            plan = next((item for item in self._plans if item.target == call.name), None)
            if plan is None:
                forwarded.append(call)
                forwarded_indices.append(index)
                continue
            plans_by_index[index] = plan
            if plan.mode in {"timeout", "error"}:
                results[index] = _failed_result(call, plan)
                continue
            forwarded.append(call)
            forwarded_indices.append(index)

        if forwarded:
            inner_results = await self._inner.dispatch(forwarded, state)
            if len(inner_results) != len(forwarded):
                raise RuntimeError("fault-decorated ToolHub returned misaligned results")
            for index, result in zip(forwarded_indices, inner_results, strict=True):
                plan = plans_by_index.get(index)
                results[index] = _stale_result(result, plan) if plan is not None else result

        if any(result is None for result in results):
            raise RuntimeError("fault decorator failed to produce one result per tool call")
        return [result for result in results if result is not None]


class DeterministicBarrier:
    """Runner-owned pause/release points for reproducible race interleavings."""

    def __init__(self) -> None:
        self._reached: dict[str, asyncio.Event] = {}
        self._released: dict[str, asyncio.Event] = {}
        self.timeline: list[dict[str, str]] = []

    async def pause(self, label: str) -> None:
        if not label.strip():
            raise ValueError("barrier label must be non-empty")
        reached = self._reached.setdefault(label, asyncio.Event())
        released = self._released.setdefault(label, asyncio.Event())
        self.timeline.append({"event": "reached", "label": label})
        reached.set()
        await released.wait()
        self.timeline.append({"event": "released", "label": label})

    async def wait_until_reached(self, label: str) -> None:
        await self._reached.setdefault(label, asyncio.Event()).wait()

    def release(self, label: str) -> None:
        if label not in self._reached or not self._reached[label].is_set():
            raise RuntimeError(f"cannot release unreached barrier {label!r}")
        self._released.setdefault(label, asyncio.Event()).set()


def _failed_result(call: StepToolCall, plan: FaultPlan) -> FaultToolResult:
    code = plan.mode
    message = str(plan.payload.get("message") or f"eval-injected {code}")
    return FaultToolResult(
        tool_name=call.name,
        args=call.parsed_args,
        success=False,
        output=None,
        error=f"[{code}] {message}",
        latency_ms=0,
        tool_call_data={"fault_injected": True, "fault_mode": code},
        error_code=code,
    )


def _stale_result(result: ToolResult, plan: FaultPlan) -> ToolResult:
    replacement = plan.payload.get("output", plan.payload)
    if not isinstance(replacement, dict):
        raise ValueError("stale fault payload must contain an object output")
    metadata = dict(result.tool_call_data or {})
    metadata.update({"fault_injected": True, "fault_mode": "stale"})
    return result.model_copy(update={"output": dict(replacement), "tool_call_data": metadata})


__all__ = [
    "FaultInjectingHub",
    "FaultMode",
    "FaultPlan",
    "FaultToolResult",
    "DeterministicBarrier",
    "TransportFaultPlan",
]
