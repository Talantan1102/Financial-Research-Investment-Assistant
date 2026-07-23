"""Closed, server-validated edits for approval-gated tool calls."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

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

    original: dict[str, Any]
    effective: dict[str, Any]


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
        return schema.model_validate(dict(arguments)).model_dump(mode="json")


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
) -> dict[str, ApprovedInput]:
    by_id = {call.id: call for call in calls}
    if set(edited_arguments) - set(by_id):
        raise ValueError("edited tool call id is unknown")
    return {
        call_id: ApprovedInput(
            original=by_id[call_id].parsed_args,
            effective=dict(arguments),
        )
        for call_id, arguments in edited_arguments.items()
    }


__all__ = [
    "ApprovalEditResponse",
    "ApprovedInput",
    "DenyEditableApprovalValidator",
    "EditableApprovalValidator",
    "SchemaEditableApprovalValidator",
    "apply_approved_edits",
    "build_approved_inputs",
    "validate_edit_ids",
]
