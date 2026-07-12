from __future__ import annotations

import pytest
from app.runtime.hooks import HookDecision, HookEvent, HookInvocation, HookPipeline
from app.runtime.models import CapabilityDefinition, CapabilityType, RiskLevel
from app.runtime.permissions import PermissionDecision, PermissionEngine
from app.runtime.validation import InputGuard, InputValidationError


def _definition(*, minimum_risk: RiskLevel = RiskLevel.LOW) -> CapabilityDefinition:
    return CapabilityDefinition(
        name="orders.submit",
        type=CapabilityType.MCP,
        input_schema={
            "type": "object",
            "properties": {
                "quantity": {"type": "integer", "minimum": 1},
                "symbol": {"type": "string"},
            },
            "required": ["quantity"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        minimum_risk=minimum_risk,
        read_only=False,
        idempotent=False,
        default_timeout_s=10,
        max_attempts=1,
    )


@pytest.mark.asyncio
async def test_pre_hooks_modify_input_in_registration_order() -> None:
    async def add_default(invocation: HookInvocation) -> HookDecision:
        return HookDecision(
            updated_input={**invocation.input, "quantity": 2}, messages=("default",)
        )

    async def double(invocation: HookInvocation) -> HookDecision:
        return HookDecision(
            updated_input={"quantity": invocation.input["quantity"] * 2}, messages=("double",)
        )

    result = await HookPipeline(pre_hooks=[add_default, double]).run_pre(
        HookInvocation(event=HookEvent.PRE, definition=_definition(), input={"symbol": "AAPL"})
    )

    assert result.updated_input == {"symbol": "AAPL", "quantity": 4}
    assert result.messages == ("default", "double")


@pytest.mark.asyncio
async def test_deny_short_circuits_remaining_hooks() -> None:
    called = False

    async def deny(_: HookInvocation) -> HookDecision:
        return HookDecision(permission=PermissionDecision.DENY)

    async def later(_: HookInvocation) -> HookDecision:
        nonlocal called
        called = True
        return HookDecision()

    result = await HookPipeline(pre_hooks=[deny, later]).run_pre(
        HookInvocation(event=HookEvent.PRE, definition=_definition(), input={"quantity": 1})
    )

    assert result.permission is PermissionDecision.DENY
    assert called is False


@pytest.mark.asyncio
async def test_hook_allow_cannot_lower_capability_minimum_ask() -> None:
    async def allow(_: HookInvocation) -> HookDecision:
        return HookDecision(permission=PermissionDecision.ALLOW)

    result = await HookPipeline(pre_hooks=[allow]).run_pre(
        HookInvocation(
            event=HookEvent.PRE,
            definition=_definition(minimum_risk=RiskLevel.MEDIUM),
            input={"quantity": 1},
        )
    )

    assert result.permission is PermissionDecision.ASK


@pytest.mark.asyncio
async def test_modified_input_is_revalidated() -> None:
    async def corrupt(_: HookInvocation) -> HookDecision:
        return HookDecision(updated_input={"quantity": 0})

    with pytest.raises(InputValidationError, match="quantity"):
        await HookPipeline(pre_hooks=[corrupt]).run_pre(
            HookInvocation(event=HookEvent.PRE, definition=_definition(), input={"quantity": 1})
        )


def test_input_guard_rejects_unknown_fields() -> None:
    with pytest.raises(InputValidationError, match="unexpected"):
        InputGuard().validate(_definition(), {"quantity": 1, "unexpected": True})


@pytest.mark.asyncio
async def test_permission_precedence_is_deny_then_ask_then_allow() -> None:
    engine = PermissionEngine()
    assert (
        await engine.authorize(_definition(), (PermissionDecision.ALLOW, PermissionDecision.DENY))
        is PermissionDecision.DENY
    )


@pytest.mark.asyncio
async def test_ask_without_authorization_callback_fails_closed() -> None:
    result = await PermissionEngine().authorize(
        _definition(), (PermissionDecision.ALLOW, PermissionDecision.ASK)
    )
    assert result is PermissionDecision.DENY


@pytest.mark.asyncio
async def test_authorization_callback_can_approve_ask() -> None:
    async def approve(_: CapabilityDefinition) -> bool:
        return True

    result = await PermissionEngine(authorization_callback=approve).authorize(
        _definition(), (PermissionDecision.ASK,)
    )
    assert result is PermissionDecision.ALLOW
