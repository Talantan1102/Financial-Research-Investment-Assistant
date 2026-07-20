"""Immutable data contracts shared by unified runtime layers."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agents.schemas import ToolResult


class FrozenDict(dict[str, Any]):
    """JSON-compatible dictionary that rejects mutation at every nesting level."""

    @staticmethod
    def _immutable(*_args: Any, **_kwargs: Any) -> None:
        raise TypeError("runtime contract mappings are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable  # type: ignore[assignment]
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable  # type: ignore[assignment]


class FrozenList(list[Any]):
    """JSON-compatible list that rejects mutation."""

    @staticmethod
    def _immutable(*_args: Any, **_kwargs: Any) -> None:
        raise TypeError("runtime contract sequences are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable
    __iadd__ = _immutable  # type: ignore[assignment]
    __imul__ = _immutable  # type: ignore[assignment]


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return FrozenDict({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return FrozenList([_deep_freeze(item) for item in value])
    if isinstance(value, set):
        return frozenset(_deep_freeze(item) for item in value)
    return value


class CapabilityType(StrEnum):
    """Kinds of capability supported by the runtime adapters."""

    DATA_TOOL = "data_tool"
    MCP = "mcp"
    SKILL = "skill"
    SUBAGENT = "subagent"
    MEMORY = "memory"


class RiskLevel(StrEnum):
    """Minimum permission risk associated with a capability."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ExecutionStatus(StrEnum):
    """Persisted task states in the bounded runtime DAG."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ErrorCategory(StrEnum):
    """Normalized runtime error categories."""

    VALIDATION_ERROR = "validation_error"
    PERMISSION_DENIED = "permission_denied"
    DEPENDENCY_FAILED = "dependency_failed"
    TIMEOUT = "timeout"
    TRANSIENT = "transient"
    EXECUTION_ERROR = "execution_error"
    RESULT_INVALID = "result_invalid"
    CANCELLED = "cancelled"
    SYSTEM_ERROR = "system_error"


class CapabilityDefinition(BaseModel):
    """Registry metadata and default execution policy for one capability."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    type: CapabilityType
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    minimum_risk: RiskLevel
    read_only: bool
    idempotent: bool
    default_timeout_s: float = Field(gt=0)
    max_attempts: int = Field(ge=1)

    def model_post_init(self, __context: Any) -> None:
        del __context
        object.__setattr__(self, "input_schema", _deep_freeze(self.input_schema))
        object.__setattr__(self, "output_schema", _deep_freeze(self.output_schema))


class ExecutionContext(BaseModel):
    """Request-scoped identity and visibility boundary for execution."""

    model_config = ConfigDict(frozen=True)

    request_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    visible_capabilities: frozenset[str] = Field(default_factory=frozenset)


class RuntimeErrorInfo(BaseModel):
    """Structured, adapter-independent execution failure."""

    model_config = ConfigDict(frozen=True)

    code: str = Field(min_length=1)
    category: ErrorCategory
    message: str = Field(min_length=1)
    retryable: bool


class RuntimeResult(BaseModel):
    """Normalized outcome returned by every capability adapter."""

    model_config = ConfigDict(frozen=True)

    status: ExecutionStatus
    output: dict[str, Any] | None = None
    error: RuntimeErrorInfo | None = None
    attempt: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    audit: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        del __context
        object.__setattr__(self, "output", _deep_freeze(self.output))
        object.__setattr__(self, "audit", _deep_freeze(self.audit))

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> RuntimeResult:
        copied = super().model_copy(update=update, deep=deep)
        object.__setattr__(copied, "output", _deep_freeze(copied.output))
        object.__setattr__(copied, "audit", _deep_freeze(copied.audit))
        return copied

    @model_validator(mode="after")
    def validate_error_matches_status(self) -> RuntimeResult:
        failed = self.status in {ExecutionStatus.FAILED, ExecutionStatus.CANCELLED}
        if failed and self.error is None:
            raise ValueError(f"error is required when status is {self.status.value}")
        if not failed and self.error is not None:
            raise ValueError(f"error is not allowed when status is {self.status.value}")
        return self

    @property
    def success(self) -> bool:
        """Whether execution reached the single successful terminal state."""

        return self.status is ExecutionStatus.SUCCEEDED

    def to_legacy(self, tool_name: str, args: dict[str, Any]) -> ToolResult:
        """Convert this outcome to the existing agent-facing result contract."""

        return ToolResult(
            tool_name=tool_name,
            args=args,
            success=self.success,
            output=self.output,
            error=self.error.message if self.error is not None else None,
            latency_ms=self.latency_ms,
            cached=bool(self.audit.get("cached", False)),
            tool_call_data=self.audit.get("tool_call_data"),
        )
