"""Ordered pre/post execution hook pipeline."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.runtime.models import CapabilityDefinition
from app.runtime.permissions import PermissionDecision, minimum_permission, strictest
from app.runtime.validation import InputGuard, InputValidationError


class HookEvent(StrEnum):
    PRE = "pre"
    POST = "post"


class HookInvocation(BaseModel):
    model_config = ConfigDict(frozen=True)

    event: HookEvent
    definition: CapabilityDefinition
    input: dict[str, Any]
    output: dict[str, Any] | None = None


class HookDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    permission: PermissionDecision = PermissionDecision.ALLOW
    updated_input: dict[str, Any] | None = None
    messages: tuple[str, ...] = Field(default_factory=tuple)


Hook = Callable[[HookInvocation], Awaitable[HookDecision]]


class HookPipeline:
    def __init__(
        self,
        *,
        pre_hooks: Sequence[Hook] = (),
        post_hooks: Sequence[Hook] = (),
        input_guard: InputGuard | None = None,
    ) -> None:
        self._pre_hooks = tuple(pre_hooks)
        self._post_hooks = tuple(post_hooks)
        self._input_guard = input_guard or InputGuard()

    async def run_pre(
        self, invocation: HookInvocation, *, validate_input: bool = True
    ) -> HookDecision:
        return await self._run(
            invocation, self._pre_hooks, validate_input=validate_input, allow_updates=True
        )

    async def run_post(self, invocation: HookInvocation) -> HookDecision:
        return await self._run(
            invocation, self._post_hooks, validate_input=False, allow_updates=False
        )

    async def _run(
        self,
        invocation: HookInvocation,
        hooks: Sequence[Hook],
        *,
        validate_input: bool,
        allow_updates: bool,
    ) -> HookDecision:
        current_input = invocation.input
        messages: list[str] = []
        decisions = [minimum_permission(invocation.definition)]

        for hook in hooks:
            decision = await hook(invocation.model_copy(update={"input": current_input}))
            messages.extend(decision.messages)
            decisions.append(decision.permission)
            if decision.updated_input is not None:
                if not allow_updates:
                    raise InputValidationError(
                        "post hook must not return updated_input after execution"
                    )
                current_input = {**current_input, **decision.updated_input}
            if strictest(decisions) is PermissionDecision.DENY:
                break

        if validate_input:
            self._input_guard.validate(invocation.definition, current_input)
        return HookDecision(
            permission=strictest(decisions),
            updated_input=current_input,
            messages=tuple(messages),
        )
