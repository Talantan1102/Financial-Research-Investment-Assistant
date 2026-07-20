"""Fail-closed permission aggregation for capability execution."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.runtime.models import CapabilityDefinition, ExecutionContext, RiskLevel


class PermissionDecision(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass(frozen=True)
class PermissionRequest:
    """The concrete capability invocation presented for user authorization."""

    capability_name: str
    risk: RiskLevel
    input: dict[str, Any]
    context: ExecutionContext


AuthorizationCallback = Callable[[PermissionRequest], Awaitable[bool]]

_PRECEDENCE = {
    PermissionDecision.ALLOW: 0,
    PermissionDecision.ASK: 1,
    PermissionDecision.DENY: 2,
}

_MINIMUM_DECISION = {
    RiskLevel.LOW: PermissionDecision.ALLOW,
    RiskLevel.MEDIUM: PermissionDecision.ASK,
    RiskLevel.HIGH: PermissionDecision.ASK,
    RiskLevel.CRITICAL: PermissionDecision.DENY,
}


def minimum_permission(definition: CapabilityDefinition) -> PermissionDecision:
    """Map capability risk to the least-strict permission decision it permits."""
    return _MINIMUM_DECISION[definition.minimum_risk]


def strictest(decisions: Iterable[PermissionDecision]) -> PermissionDecision:
    """Return the most restrictive decision, defaulting to allow."""
    return max(decisions, key=_PRECEDENCE.__getitem__, default=PermissionDecision.ALLOW)


class PermissionEngine:
    def __init__(self, authorization_callback: AuthorizationCallback | None = None) -> None:
        self._authorization_callback = authorization_callback

    async def authorize(
        self,
        definition: CapabilityDefinition,
        input: dict[str, Any],
        context: ExecutionContext,
        decisions: Iterable[PermissionDecision] = (),
    ) -> PermissionDecision:
        decision = strictest((*decisions, minimum_permission(definition)))
        if decision is not PermissionDecision.ASK:
            return decision
        if self._authorization_callback is None:
            return PermissionDecision.DENY
        approved = await self._authorization_callback(
            PermissionRequest(
                capability_name=definition.name,
                risk=definition.minimum_risk,
                input=input,
                context=context,
            )
        )
        return PermissionDecision.ALLOW if approved else PermissionDecision.DENY
