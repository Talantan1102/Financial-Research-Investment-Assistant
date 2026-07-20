from typing import Any

import pytest
from app.runtime.models import (
    CapabilityDefinition,
    CapabilityType,
    ErrorCategory,
    ExecutionContext,
    ExecutionStatus,
    RiskLevel,
    RuntimeErrorInfo,
    RuntimeResult,
)
from pydantic import ValidationError


def test_runtime_enums_serialize_to_contract_values() -> None:
    capability = CapabilityDefinition(
        name="market.quote",
        type=CapabilityType.DATA_TOOL,
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        minimum_risk=RiskLevel.LOW,
        read_only=True,
        idempotent=True,
        default_timeout_s=10.0,
        max_attempts=2,
    )
    result = RuntimeResult(
        status=ExecutionStatus.FAILED,
        error=RuntimeErrorInfo(
            code="upstream_unavailable",
            category=ErrorCategory.TRANSIENT,
            message="market data provider unavailable",
            retryable=True,
        ),
        attempt=1,
        latency_ms=12,
    )

    assert capability.model_dump(mode="json")["type"] == "data_tool"
    assert capability.model_dump(mode="json")["minimum_risk"] == "low"
    assert result.model_dump(mode="json")["status"] == "failed"
    assert result.model_dump(mode="json")["error"]["category"] == "transient"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (ExecutionStatus.PENDING, False),
        (ExecutionStatus.RUNNING, False),
        (ExecutionStatus.SUCCEEDED, True),
        (ExecutionStatus.FAILED, False),
        (ExecutionStatus.CANCELLED, False),
    ],
)
def test_success_is_derived_from_execution_status(status: ExecutionStatus, expected: bool) -> None:
    kwargs: dict[str, Any] = {}
    if status in {ExecutionStatus.FAILED, ExecutionStatus.CANCELLED}:
        kwargs["error"] = RuntimeErrorInfo(
            code="stopped",
            category=(
                ErrorCategory.CANCELLED
                if status is ExecutionStatus.CANCELLED
                else ErrorCategory.EXECUTION_ERROR
            ),
            message="execution stopped",
            retryable=False,
        )

    result = RuntimeResult(status=status, **kwargs)

    assert result.success is expected
    assert "success" not in result.model_dump()


def test_failed_result_requires_error() -> None:
    with pytest.raises(ValidationError, match="error"):
        RuntimeResult(status=ExecutionStatus.FAILED)


def test_cancelled_result_requires_error() -> None:
    with pytest.raises(ValidationError, match="error"):
        RuntimeResult(status=ExecutionStatus.CANCELLED)


def test_successful_result_rejects_error() -> None:
    with pytest.raises(ValidationError, match="error"):
        RuntimeResult(
            status=ExecutionStatus.SUCCEEDED,
            error=RuntimeErrorInfo(
                code="impossible",
                category=ErrorCategory.SYSTEM_ERROR,
                message="must not coexist with success",
                retryable=False,
            ),
        )


def test_runtime_contract_models_are_frozen() -> None:
    context = ExecutionContext(
        request_id="request-1",
        turn_id="turn-1",
        task_id="task-1",
        user_id="user-1",
        visible_capabilities=frozenset({"market.quote"}),
    )

    with pytest.raises(ValidationError, match="frozen"):
        context.task_id = "other"  # type: ignore[misc]


def test_runtime_contract_nested_mappings_are_deeply_immutable() -> None:
    capability = CapabilityDefinition(
        name="quote",
        type=CapabilityType.DATA_TOOL,
        input_schema={"type": "object", "properties": {"symbol": {"type": "string"}}},
        output_schema={"type": "object"},
        minimum_risk=RiskLevel.LOW,
        read_only=True,
        idempotent=True,
        default_timeout_s=1,
        max_attempts=1,
    )
    result = RuntimeResult(
        status=ExecutionStatus.SUCCEEDED,
        output={"nested": {"price": 1}},
        audit={"labels": {"source": "runtime"}},
    )

    with pytest.raises(TypeError):
        capability.input_schema["properties"]["symbol"]["type"] = "integer"
    with pytest.raises(TypeError):
        result.output["nested"]["price"] = 2  # type: ignore[index]
    with pytest.raises(TypeError):
        result.audit["labels"]["source"] = "mutated"

    copied = result.model_copy(update={"audit": {"new": {"nested": True}}})
    with pytest.raises(TypeError):
        copied.audit["new"]["nested"] = False


def test_runtime_result_converts_to_legacy_tool_result() -> None:
    result = RuntimeResult(
        status=ExecutionStatus.SUCCEEDED,
        output={"price": 101.5},
        attempt=2,
        latency_ms=24,
        audit={"cached": True, "tool_call_data": {"source": "runtime"}},
    )

    legacy = result.to_legacy("market.quote", {"symbol": "600519.SH"})

    assert legacy.tool_name == "market.quote"
    assert legacy.args == {"symbol": "600519.SH"}
    assert legacy.success is True
    assert legacy.output == {"price": 101.5}
    assert legacy.error is None
    assert legacy.latency_ms == 24
    assert legacy.cached is True
    assert legacy.tool_call_data == {"source": "runtime"}


def test_failed_runtime_result_converts_error_message_to_legacy() -> None:
    result = RuntimeResult(
        status=ExecutionStatus.FAILED,
        error=RuntimeErrorInfo(
            code="provider_timeout",
            category=ErrorCategory.TIMEOUT,
            message="provider timed out",
            retryable=True,
        ),
        latency_ms=5000,
    )

    legacy = result.to_legacy("market.quote", {})

    assert legacy.success is False
    assert legacy.error == "provider timed out"
    assert legacy.output is None
