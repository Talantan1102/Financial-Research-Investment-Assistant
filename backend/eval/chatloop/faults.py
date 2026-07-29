"""Evaluation-only fault decorators for real conversational execution paths."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from app.agents.schemas import ToolResult
from app.chatloop.state import ChatLoopState
from app.services.llm_step import StepToolCall

from eval.chatloop.case_schema import (
    validate_approval_delay_fault,
    validate_approval_pause_fault,
    validate_suspended_quote_fault,
)

FaultMode = Literal[
    "timeout",
    "error",
    "stale",
    "conflict",
    "approval_pause",
    "approval_delay",
    "suspended_quote",
    "response_lost_after_commit",
    "duplicate_approval_resume",
]


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
        if self.mode == "approval_pause":
            validate_approval_pause_fault(self.target, self.payload)
        elif self.mode == "approval_delay":
            validate_approval_delay_fault(self.target, self.payload)
        elif self.mode == "suspended_quote":
            validate_suspended_quote_fault(self.target, self.payload)


@dataclass(frozen=True, slots=True)
class TransportFaultPlan:
    """Faults around durable HTTP actions, never inside production services."""

    duplicate_approval_resume: bool = False

    @property
    def retry_policy(self) -> Literal["normal"]:
        return "normal"


class FaultToolResult(ToolResult):
    """A normal ToolResult with an evaluator-readable deterministic error code."""

    error_code: str


class FaultInjectingHub:
    """Decorate a real ToolHub without exposing fault controls to the Agent."""

    def __init__(self, inner: ToolHubLike, plans: list[FaultPlan]) -> None:
        self._inner = inner
        self._plans = tuple(plans)
        self._matched_attempts = [0 for _plan in self._plans]
        dedicated_modes = sorted(
            {
                plan.mode
                for plan in self._plans
                if plan.mode
                in {
                    "approval_pause",
                    "approval_delay",
                    "suspended_quote",
                    "duplicate_approval_resume",
                }
            }
        )
        if dedicated_modes:
            raise ValueError(f"{', '.join(dedicated_modes)} requires a dedicated runner hook")
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
        for plan in self._plans:
            _validate_fault_selectors(plan)

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
        post_commit_faults: dict[int, FaultPlan] = {}

        for index, call in enumerate(calls):
            plan: FaultPlan | None = None
            for plan_index, candidate in enumerate(self._plans):
                if candidate.target != call.name:
                    continue
                if not _arguments_match(
                    call.parsed_args,
                    candidate.payload.get("match_arguments", {}),
                ):
                    continue
                self._matched_attempts[plan_index] += 1
                if _attempt_is_selected(candidate, self._matched_attempts[plan_index]):
                    plan = candidate
                    break
            if plan is None:
                forwarded.append(call)
                forwarded_indices.append(index)
                continue
            if plan.mode == "response_lost_after_commit":
                forwarded.append(call)
                forwarded_indices.append(index)
                post_commit_faults[index] = plan
                continue
            if plan.mode in {"timeout", "error"}:
                results[index] = _failed_result(call, plan)
                continue
            results[index] = _stale_result(call, plan)

        if forwarded:
            inner_results = await self._inner.dispatch(forwarded, state)
            if len(inner_results) != len(forwarded):
                raise RuntimeError("fault-decorated ToolHub returned misaligned results")
            for index, result in zip(forwarded_indices, inner_results, strict=True):
                plan = post_commit_faults.get(index)
                results[index] = (
                    _lost_after_commit_result(calls[index], result, plan)
                    if plan is not None and result.success
                    else result
                )

        if any(result is None for result in results):
            raise RuntimeError("fault decorator failed to produce one result per tool call")
        return [result for result in results if result is not None]


def _validate_fault_selectors(plan: FaultPlan) -> None:
    match_arguments = plan.payload.get("match_arguments", {})
    if not isinstance(match_arguments, Mapping):
        raise ValueError("fault match_arguments must be an object")
    attempts = plan.payload.get("apply_on_attempts")
    if attempts is None:
        return
    if (
        not isinstance(attempts, Sequence)
        or isinstance(attempts, (str, bytes, bytearray))
        or not attempts
        or any(type(value) is not int or value < 1 for value in attempts)
    ):
        raise ValueError("fault apply_on_attempts must contain positive integers")


def _arguments_match(actual: Mapping[str, Any], expected: Any) -> bool:
    if not isinstance(expected, Mapping):
        return False
    return all(key in actual and actual[key] == value for key, value in expected.items())


def _attempt_is_selected(plan: FaultPlan, attempt: int) -> bool:
    selected = plan.payload.get("apply_on_attempts")
    return selected is None or attempt in selected


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


def _stale_result(call: StepToolCall, plan: FaultPlan) -> ToolResult:
    replacement = plan.payload.get("output", plan.payload)
    if not isinstance(replacement, dict):
        raise ValueError("stale fault payload must contain an object output")
    return ToolResult(
        tool_name=call.name,
        args=call.parsed_args,
        success=True,
        output=dict(replacement),
        error=None,
        latency_ms=0,
        tool_call_data={"fault_injected": True, "fault_mode": "stale"},
    )


def _lost_after_commit_result(
    call: StepToolCall,
    committed: ToolResult,
    plan: FaultPlan,
) -> FaultToolResult:
    message = str(
        plan.payload.get("message") or "tool response was lost after the production write committed"
    )
    return FaultToolResult(
        tool_name=call.name,
        args=call.parsed_args,
        success=False,
        output=None,
        error=f"[response_lost_after_commit] {message}",
        latency_ms=committed.latency_ms,
        tool_call_data={
            "fault_injected": True,
            "fault_mode": "response_lost_after_commit",
            "committed_result_observed_by_evaluator": committed.output,
        },
        error_code="response_lost_after_commit",
    )


__all__ = [
    "FaultInjectingHub",
    "FaultMode",
    "FaultPlan",
    "FaultToolResult",
    "DeterministicBarrier",
    "TransportFaultPlan",
]
