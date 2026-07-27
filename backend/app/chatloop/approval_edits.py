"""Closed, server-validated edits for approval-gated tool calls."""

from __future__ import annotations

import json
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from app.services.llm_step import StepToolCall


class ApprovalEditResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool
    text: str | None = None
    edited_arguments: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_edits_without_approval(self) -> ApprovalEditResponse:
        if not self.approved and self.edited_arguments:
            raise ValueError("rejected approval cannot edit arguments")
        return self


class ApprovedInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    original: Mapping[str, Any]
    effective: Mapping[str, Any]

    def model_post_init(self, __context: Any) -> None:
        del __context
        object.__setattr__(self, "original", _deep_freeze(self.original))
        object.__setattr__(self, "effective", _deep_freeze(self.effective))

    @field_serializer("original", "effective")
    def serialize_frozen_mapping(self, value: Mapping[str, Any]) -> dict[str, Any]:
        thawed = thaw_approved_value(value)
        assert isinstance(thawed, dict)
        return thawed


class EditableApprovalValidator(Protocol):
    def validate(
        self,
        *,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]: ...


class DenyEditableApprovalValidator:
    def validate(
        self,
        *,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        del tool_name, arguments
        raise ValueError("tool arguments are not editable")


class SchemaEditableApprovalValidator:
    def __init__(self, schemas: Mapping[str, type[BaseModel]]) -> None:
        self._schemas = dict(schemas)

    def validate(
        self,
        *,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        schema = self._schemas.get(tool_name)
        if schema is None:
            raise ValueError("tool arguments are not editable")
        normalized = schema.model_validate(dict(arguments)).model_dump(mode="json")
        return normalize_standard_json_object(normalized)


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_deep_freeze(item) for item in value)
    return value


def thaw_approved_value(value: Any) -> Any:
    """Return an explicit mutable copy for business DTO construction."""

    if isinstance(value, Mapping):
        return {key: thaw_approved_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_approved_value(item) for item in value]
    if isinstance(value, frozenset):
        return {thaw_approved_value(item) for item in value}
    return value


def normalize_standard_json_object(value: Mapping[str, Any]) -> dict[str, Any]:
    """Defensively copy a mapping through strict RFC-compatible JSON."""

    encoded = json.dumps(
        dict(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    normalized = json.loads(encoded)
    if not isinstance(normalized, dict):
        raise ValueError("approval arguments must be a JSON object")
    return normalized


def apply_approved_edits(
    calls: tuple[StepToolCall, ...],
    edited_arguments: Mapping[str, Mapping[str, Any]],
) -> tuple[StepToolCall, ...]:
    return tuple(
        call.model_copy(
            update={
                "arguments": json.dumps(
                    edited_arguments[call.id],
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            }
        )
        if call.id in edited_arguments
        else call
        for call in calls
    )


def validate_edit_ids(
    *,
    requested_ids: set[str] | frozenset[str],
    editable_ids: set[str] | frozenset[str],
    edited_arguments: Mapping[str, Mapping[str, Any]],
) -> None:
    edit_ids = set(edited_arguments)
    if not edit_ids.issubset(requested_ids):
        raise ValueError("unknown tool call id")
    if not edit_ids.issubset(editable_ids):
        raise ValueError("tool call is not editable")


def build_approved_inputs(
    calls: tuple[StepToolCall, ...],
    edited_arguments: Mapping[str, Mapping[str, Any]],
    *,
    approved_ids: set[str] | frozenset[str] | None = None,
) -> dict[str, ApprovedInput]:
    by_id = {call.id: call for call in calls}
    selected_ids = set(edited_arguments) if approved_ids is None else set(approved_ids)
    if (set(edited_arguments) | selected_ids) - set(by_id):
        raise ValueError("edited tool call id is unknown")
    return {
        call_id: ApprovedInput(
            original=by_id[call_id].parsed_args,
            effective=dict(edited_arguments.get(call_id, by_id[call_id].parsed_args)),
        )
        for call_id in selected_ids
    }


__all__ = [
    "ApprovalEditResponse",
    "ApprovedInput",
    "DenyEditableApprovalValidator",
    "EditableApprovalValidator",
    "SchemaEditableApprovalValidator",
    "apply_approved_edits",
    "build_approved_inputs",
    "normalize_standard_json_object",
    "thaw_approved_value",
    "validate_edit_ids",
]
