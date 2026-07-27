"""Portable, versioned snapshots for resuming a chat attempt on any Worker."""

from __future__ import annotations

import json
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.chatloop.state import ChatLoopState, LedgerEntry, ToolLedger
from app.services.llm_step import StepToolCall

MAX_CONTINUATION_BYTES = 64 * 1024
_MAX_NODES = 10_000
_MAX_DEPTH = 64


def _validate_portable(value: Any) -> None:
    stack = [(value, 0)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_NODES or depth > _MAX_DEPTH:
            raise ValueError("continuation structure exceeds limits")
        if current is None or type(current) in (str, bool):
            continue
        if type(current) is int:
            if abs(current) > 2**63 - 1:
                raise ValueError("integer outside portable range")
            continue
        if type(current) is float:
            if not math.isfinite(current):
                raise ValueError("non-finite float")
            continue
        if type(current) is dict:
            for key, item in current.items():
                if not isinstance(key, str):
                    raise ValueError("JSON object keys must be strings")
                stack.append((item, depth + 1))
            continue
        if type(current) in (list, tuple):
            stack.extend((item, depth + 1) for item in current)
            continue
        raise TypeError("continuation contains a runtime object")


class CompactLedgerEntryV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    step: int = Field(strict=True, ge=0)
    tool_call_id: str | None = Field(default=None, max_length=255)
    tool_name: str = Field(min_length=1, max_length=255)
    args_hash: str = Field(min_length=1, max_length=64)
    digest: str = Field(max_length=200)
    success: bool = Field(strict=True)
    cache_key: str | None = Field(default=None, max_length=1024)


class ToolFunctionV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=255)
    arguments: str


class ToolCallV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=255)
    type: Literal["function"] = "function"
    function: ToolFunctionV1


class MessageV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: tuple[ToolCallV1, ...] = Field(default=(), max_length=64)
    tool_call_id: str | None = Field(default=None, max_length=255)
    name: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_role_shape(self) -> MessageV1:
        if self.role == "assistant":
            if self.tool_call_id is not None:
                raise ValueError("assistant message cannot have tool_call_id")
        elif self.role == "tool":
            if not self.tool_call_id or self.tool_calls:
                raise ValueError("tool message requires tool_call_id only")
        elif self.tool_calls or self.tool_call_id is not None or self.reasoning_content is not None:
            raise ValueError("message fields do not match role")
        return self


class PendingToolCallV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    arguments: str
    risk_level: Literal["low", "high"] | None = None
    permission_decision: Literal["direct", "approval_required"] | None = None

    def to_step_tool_call(self) -> StepToolCall:
        return StepToolCall(id=self.id, name=self.name, arguments=self.arguments)


class RecoveryToolCallV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    arguments: dict[str, Any]


class ExecutionBindingV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_id: str = Field(min_length=1, max_length=64)
    semantic_key: str = Field(min_length=1, max_length=128)
    tool_call: RecoveryToolCallV1


class PauseRequestV1(BaseModel):
    """Closed portable shape used by input, risk approval and recovery approval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str | None = Field(default=None, max_length=255)
    question: str | None = Field(default=None, max_length=4096)
    reason: str | None = Field(default=None, max_length=255)
    action: str | None = Field(default=None, max_length=255)
    risk_level: Literal["low", "high"] | None = None
    permission_decision: Literal["direct", "approval_required"] | None = None
    tool_calls: tuple[PendingToolCallV1, ...] = Field(default=(), max_length=64)
    editable_tool_call_ids: tuple[str, ...] = Field(default=(), max_length=64)
    execution_bindings: tuple[ExecutionBindingV1, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def validate_editable_tool_calls(self) -> PauseRequestV1:
        tool_call_ids = {call.id for call in self.tool_calls}
        if len(set(self.editable_tool_call_ids)) != len(self.editable_tool_call_ids) or not set(
            self.editable_tool_call_ids
        ).issubset(tool_call_ids):
            raise ValueError("editable tool call ids must be a unique subset of tool calls")
        return self


class PendingActionV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pause_type: Literal["input", "approval"]
    tool_name: Literal["ask_user", "approve_tools"]
    request: PauseRequestV1
    pending_tool_calls: tuple[PendingToolCallV1, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def validate_action(self) -> PendingActionV1:
        if self.pause_type == "input" and self.pending_tool_calls:
            raise ValueError("input pause cannot contain pending tool calls")
        if self.pause_type == "approval" and not self.pending_tool_calls:
            raise ValueError("approval pause requires pending tool calls")
        _validate_portable(self.request.model_dump(mode="json"))
        return self

    def step_tool_calls(self) -> tuple[StepToolCall, ...]:
        return tuple(call.to_step_tool_call() for call in self.pending_tool_calls)


class ContinuationBodyV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1, max_length=64)
    session_id: str = Field(min_length=1, max_length=64)
    user_id: str = Field(min_length=1, max_length=64)
    tenant_id: str = Field(min_length=1, max_length=64)
    messages: tuple[MessageV1, ...] = Field(max_length=512)
    tool_ledger: tuple[CompactLedgerEntryV1, ...] = ()
    loop_count: int = Field(strict=True, ge=0, le=10_000)
    budget_spent_cny: float = Field(strict=True, ge=0)
    budget_spent_tokens: int = Field(strict=True, ge=0)
    prompt_tokens_total: int = Field(strict=True, ge=0)
    completion_tokens_total: int = Field(strict=True, ge=0)
    cached_tokens_total: int = Field(strict=True, ge=0)
    burned_signatures: tuple[str, ...] = Field(max_length=10_000)
    pending_action: PendingActionV1


class ContinuationV1(BaseModel):
    """Authenticated envelope whose body contains only portable loop state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    key_id: str = Field(min_length=1, max_length=128)
    body: ContinuationBodyV1
    signature: str = Field(min_length=64, max_length=64)

    @property
    def pending_action(self) -> PendingActionV1:
        return self.body.pending_action

    @model_validator(mode="before")
    @classmethod
    def validate_portability_and_size(cls, value: Any) -> Any:
        _validate_portable(value)
        if type(value) is not dict or type(value.get("version")) is not int:
            raise ValueError("continuation version must be the integer 1")
        try:
            encoded = json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("continuation is not portable JSON") from exc
        if len(encoded) > MAX_CONTINUATION_BYTES:
            raise ValueError("continuation exceeds byte limit")
        return value

    @classmethod
    def from_state(
        cls,
        state: ChatLoopState,
        pending_action: PendingActionV1,
        *,
        key_id: str,
        signature: str,
        tenant_id: str,
    ) -> ContinuationV1:
        body = ContinuationBodyV1(
            run_id=state.request_id,
            session_id=state.session_id,
            user_id=state.user_id,
            tenant_id=tenant_id,
            messages=tuple(MessageV1.model_validate(message) for message in state.messages),
            tool_ledger=tuple(
                CompactLedgerEntryV1.model_validate(entry.model_dump(mode="python"))
                for entry in state.ledger.entries
            ),
            loop_count=state.step,
            budget_spent_cny=state.budget_spent_cny,
            budget_spent_tokens=state.budget_spent_tokens,
            prompt_tokens_total=state.prompt_tokens_total,
            completion_tokens_total=state.completion_tokens_total,
            cached_tokens_total=state.cached_tokens_total,
            burned_signatures=tuple(sorted(state.burned_signatures)),
            pending_action=pending_action,
        )
        return cls.model_validate(
            {
                "version": 1,
                "key_id": key_id,
                "body": body.model_dump(mode="json"),
                "signature": signature,
            }
        )

    def to_state(self) -> ChatLoopState:
        state = ChatLoopState(
            user_id=self.body.user_id,
            session_id=self.body.session_id,
            request_id=self.body.run_id,
            messages=[
                message.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
                for message in self.body.messages
            ],
            step=self.body.loop_count,
            budget_spent_cny=self.body.budget_spent_cny,
            budget_spent_tokens=self.body.budget_spent_tokens,
            prompt_tokens_total=self.body.prompt_tokens_total,
            completion_tokens_total=self.body.completion_tokens_total,
            cached_tokens_total=self.body.cached_tokens_total,
            burned_signatures=set(self.body.burned_signatures),
        )
        state.ledger = ToolLedger(
            entries=[
                LedgerEntry.model_validate(entry.model_dump(mode="python"))
                for entry in self.body.tool_ledger
            ]
        )
        return state


__all__ = [
    "CompactLedgerEntryV1",
    "ContinuationBodyV1",
    "ContinuationV1",
    "MAX_CONTINUATION_BYTES",
    "PendingActionV1",
    "MessageV1",
    "PauseRequestV1",
]
