import asyncio
from typing import Any

import pytest
from app.runtime.hooks import HookDecision, HookPipeline
from app.runtime.models import (
    CapabilityDefinition,
    CapabilityType,
    ErrorCategory,
    ExecutionContext,
    ExecutionStatus,
    RiskLevel,
    RuntimeResult,
)
from app.runtime.permissions import PermissionEngine
from app.runtime.registry import CapabilityRegistry
from app.runtime.safe_executor import SafeExecutor
from app.runtime.tool_runtime import ToolRuntime
from app.runtime.validation import InputGuard


def definition(*, timeout: float = 1, risk: RiskLevel = RiskLevel.LOW) -> CapabilityDefinition:
    return CapabilityDefinition(
        name="quote",
        type=CapabilityType.DATA_TOOL,
        input_schema={
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        minimum_risk=risk,
        read_only=True,
        idempotent=True,
        default_timeout_s=timeout,
        max_attempts=1,
    )


def context(*, visible: bool = True) -> ExecutionContext:
    return ExecutionContext(
        request_id="request",
        turn_id="turn",
        task_id="task",
        user_id="user",
        visible_capabilities=frozenset({"quote"} if visible else ()),
    )


class Adapter:
    def __init__(self, events: list[str], output: dict[str, Any] | None = None) -> None:
        self.events = events
        self.output = output or {"price": 1}
        self.calls = 0

    async def execute(self, input: dict[str, Any], context: ExecutionContext) -> RuntimeResult:
        self.calls += 1
        self.events.append(f"adapter:{input['symbol']}")
        return RuntimeResult(status=ExecutionStatus.SUCCEEDED, output=self.output)


@pytest.mark.asyncio
async def test_pipeline_uses_effective_input_in_strict_order() -> None:
    events: list[str] = []
    adapter = Adapter(events)
    registry = CapabilityRegistry()
    registry.register(definition(risk=RiskLevel.MEDIUM), adapter)

    async def pre(invocation: Any) -> HookDecision:
        events.append("pre")
        return HookDecision(updated_input={"symbol": "MSFT"})

    async def authorize(_definition: CapabilityDefinition) -> bool:
        events.append("permission")
        return True

    class Guard(InputGuard):
        def validate(
            self, definition: CapabilityDefinition, invocation_input: dict[str, Any]
        ) -> dict[str, Any]:
            events.append(f"validation:{invocation_input['symbol']}")
            return super().validate(definition, invocation_input)

    async def post(invocation: Any) -> HookDecision:
        events.append(f"post:{invocation.output['price']}")
        return HookDecision()

    runtime = ToolRuntime(
        registry,
        hooks=HookPipeline(pre_hooks=[pre], post_hooks=[post]),
        permissions=PermissionEngine(authorize),
        input_guard=Guard(),
    )
    result = await runtime.execute("quote", {"symbol": "AAPL"}, context())

    assert result.success
    assert events == ["pre", "permission", "validation:MSFT", "adapter:MSFT", "post:1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("visible,risk", [(False, RiskLevel.LOW), (True, RiskLevel.CRITICAL)])
async def test_front_gate_rejection_never_calls_adapter(visible: bool, risk: RiskLevel) -> None:
    adapter = Adapter([])
    registry = CapabilityRegistry()
    registry.register(definition(risk=risk), adapter)
    result = await ToolRuntime(registry).execute(
        "quote", {"symbol": "AAPL"}, context(visible=visible)
    )
    assert not result.success
    assert adapter.calls == 0


@pytest.mark.asyncio
async def test_invalid_pre_hook_update_never_calls_adapter() -> None:
    adapter = Adapter([])
    registry = CapabilityRegistry()
    registry.register(definition(), adapter)

    async def corrupt(_invocation: Any) -> HookDecision:
        return HookDecision(updated_input={"symbol": 42})

    result = await ToolRuntime(registry, hooks=HookPipeline(pre_hooks=[corrupt])).execute(
        "quote", {"symbol": "AAPL"}, context()
    )
    assert result.error is not None and result.error.category is ErrorCategory.VALIDATION_ERROR
    assert adapter.calls == 0


@pytest.mark.asyncio
async def test_post_hook_failure_downgrades_success() -> None:
    adapter = Adapter([])
    registry = CapabilityRegistry()
    registry.register(definition(), adapter)

    async def corrupt(_invocation: Any) -> HookDecision:
        return HookDecision(updated_input={"symbol": "changed"})

    result = await ToolRuntime(registry, hooks=HookPipeline(post_hooks=[corrupt])).execute(
        "quote", {"symbol": "AAPL"}, context()
    )
    assert result.status is ExecutionStatus.FAILED
    assert result.error is not None and result.error.category is ErrorCategory.SYSTEM_ERROR


@pytest.mark.asyncio
async def test_safe_executor_classifies_timeout_cancel_exception_and_output_limit() -> None:
    class Slow:
        async def execute(self, input: dict[str, Any], context: ExecutionContext) -> RuntimeResult:
            await asyncio.sleep(1)
            raise AssertionError("unreachable")

    class Boom:
        async def execute(self, input: dict[str, Any], context: ExecutionContext) -> RuntimeResult:
            raise ValueError("boom")

    class Cancel:
        async def execute(self, input: dict[str, Any], context: ExecutionContext) -> RuntimeResult:
            raise asyncio.CancelledError

    executor = SafeExecutor(max_output_bytes=10)
    timeout = await executor.execute(Slow(), {}, context(), timeout_s=0.001)
    failed = await executor.execute(Boom(), {}, context(), timeout_s=1)
    cancelled = await executor.execute(Cancel(), {}, context(), timeout_s=1)
    oversized = await executor.execute(
        Adapter([], {"large": "x" * 20}), {"symbol": "AAPL"}, context(), timeout_s=1
    )
    assert timeout.error is not None and timeout.error.category is ErrorCategory.TIMEOUT
    assert failed.error is not None and failed.error.category is ErrorCategory.EXECUTION_ERROR
    assert cancelled.status is ExecutionStatus.CANCELLED
    assert cancelled.error is not None and cancelled.error.category is ErrorCategory.CANCELLED
    assert oversized.error is not None and oversized.error.category is ErrorCategory.RESULT_INVALID


@pytest.mark.asyncio
async def test_safe_executor_classifies_non_json_output_as_result_invalid() -> None:
    result = await SafeExecutor().execute(
        Adapter([], {"bad": object()}),
        {"symbol": "AAPL"},
        context(),
        timeout_s=1,
    )
    assert result.error is not None
    assert result.error.category is ErrorCategory.RESULT_INVALID
