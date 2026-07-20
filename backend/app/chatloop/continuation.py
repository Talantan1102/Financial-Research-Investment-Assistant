"""Portable, versioned snapshots for resuming a chat attempt on any Worker."""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Mapping
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
        if current is None or isinstance(current, (str, bool)):
            continue
        if isinstance(current, int):
            if abs(current) > 2**63 - 1:
                raise ValueError("integer outside portable range")
            continue
        if isinstance(current, float):
            if not math.isfinite(current):
                raise ValueError("non-finite float")
            continue
        if isinstance(current, Mapping):
            for key, item in current.items():
                if not isinstance(key, str):
                    raise ValueError("JSON object keys must be strings")
                stack.append((item, depth + 1))
            continue
        if isinstance(current, (list, tuple)):
            stack.extend((item, depth + 1) for item in current)
            continue
        raise TypeError("continuation contains a runtime object")


class CompactLedgerEntryV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    step: int = Field(ge=0)
    tool_call_id: str | None = None
    tool_name: str
    args_hash: str
    digest: str = Field(max_length=200)
    success: bool
    cache_key: str | None = None


class PendingActionV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pause_type: Literal["input", "approval"]
    tool_name: str
    request: dict[str, Any]
    pending_tool_calls: tuple[StepToolCall, ...] = ()

    @model_validator(mode="after")
    def validate_action(self) -> PendingActionV1:
        if self.pause_type == "input" and self.pending_tool_calls:
            raise ValueError("input pause cannot contain pending tool calls")
        if self.pause_type == "approval" and not self.pending_tool_calls:
            raise ValueError("approval pause requires pending tool calls")
        _validate_portable(self.request)
        return self


class ContinuationBodyV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    session_id: str
    user_id: str
    messages: tuple[dict[str, Any], ...]
    tool_ledger: tuple[CompactLedgerEntryV1, ...] = ()
    loop_count: int = Field(ge=0)
    pending_action: PendingActionV1


class ContinuationV1(BaseModel):
    """Authenticated envelope whose body contains only portable loop state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    key_id: str
    body: ContinuationBodyV1
    signature: str = Field(min_length=64, max_length=64)

    @property
    def pending_action(self) -> PendingActionV1:
        return self.body.pending_action

    @model_validator(mode="before")
    @classmethod
    def validate_portability_and_size(cls, value: Any) -> Any:
        _validate_portable(value)
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
    ) -> ContinuationV1:
        body = ContinuationBodyV1(
            run_id=state.request_id,
            session_id=state.session_id,
            user_id=state.user_id,
            messages=tuple(state.messages),
            tool_ledger=tuple(
                CompactLedgerEntryV1.model_validate(entry.model_dump(mode="python"))
                for entry in state.ledger.entries
            ),
            loop_count=state.step,
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
            messages=copy.deepcopy(list(self.body.messages)),
            step=self.body.loop_count,
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
]
