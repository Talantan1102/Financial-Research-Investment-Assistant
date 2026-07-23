from __future__ import annotations

import json
from decimal import Decimal

import pytest
from app.chatloop.approval_edits import (
    ApprovalEditResponse,
    SchemaEditableApprovalValidator,
    apply_approved_edits,
    build_approved_inputs,
    validate_edit_ids,
)
from app.chatloop.continuation import PauseRequestV1
from app.chatloop.inprocess import InProcessTool
from app.chatloop.state import ChatLoopState
from app.chatloop.tool_runtime_adapter import ChatloopToolAdapter
from app.runtime.models import ExecutionContext
from app.services.llm_step import StepToolCall
from pydantic import BaseModel, ValidationError


def test_closed_approval_response_rejects_edits_on_rejection() -> None:
    with pytest.raises(ValidationError, match="cannot edit"):
        ApprovalEditResponse.model_validate(
            {
                "approved": False,
                "edited_arguments": {"trade-1": {"quantity": 200}},
            }
        )

    with pytest.raises(ValidationError, match="Extra inputs"):
        ApprovalEditResponse.model_validate({"approved": True, "surprise": True})


def test_pause_editable_ids_must_be_requested_tool_call_subset() -> None:
    accepted = PauseRequestV1.model_validate(
        {
            "tool_calls": [
                {"id": "trade-1", "name": "place_paper_order", "arguments": "{}"}
            ],
            "editable_tool_call_ids": ["trade-1"],
        }
    )
    assert accepted.editable_tool_call_ids == ("trade-1",)

    with pytest.raises(ValidationError, match="editable"):
        PauseRequestV1.model_validate(
            {
                "tool_calls": [
                    {"id": "trade-1", "name": "place_paper_order", "arguments": "{}"}
                ],
                "editable_tool_call_ids": ["other"],
            }
        )


def test_approved_edits_keep_original_calls_and_build_frozen_audit_inputs() -> None:
    calls = (
        StepToolCall(
            id="trade-1",
            name="place_paper_order",
            arguments='{"quantity":100,"ts_code":"600519.SH"}',
        ),
    )
    edits = {"trade-1": {"ts_code": "600519.SH", "quantity": 200}}

    effective = apply_approved_edits(calls, edits)
    approved = build_approved_inputs(calls, edits)

    assert calls[0].parsed_args == {"quantity": 100, "ts_code": "600519.SH"}
    assert effective[0].id == calls[0].id
    assert effective[0].name == calls[0].name
    assert effective[0].arguments == '{"quantity":200,"ts_code":"600519.SH"}'
    assert approved["trade-1"].original == {
        "quantity": 100,
        "ts_code": "600519.SH",
    }
    assert approved["trade-1"].effective == {
        "quantity": 200,
        "ts_code": "600519.SH",
    }
    with pytest.raises(ValidationError):
        approved["trade-1"].effective = {}  # type: ignore[misc]


def test_edit_for_unknown_or_noneditable_call_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown tool call"):
        validate_edit_ids(
            requested_ids={"trade-1"},
            editable_ids={"trade-1"},
            edited_arguments={"other": {"quantity": 200}},
        )
    with pytest.raises(ValueError, match="not editable"):
        validate_edit_ids(
            requested_ids={"trade-1"},
            editable_ids=set(),
            edited_arguments={"trade-1": {"quantity": 200}},
        )


def test_approved_inputs_are_attempt_local_and_excluded_from_state_snapshot() -> None:
    calls = (
        StepToolCall(id="trade-1", name="place_paper_order", arguments='{"quantity":100}'),
    )
    state = ChatLoopState(
        user_id="u",
        session_id="s",
        request_id="r",
        messages=[],
        approved_inputs=build_approved_inputs(calls, {"trade-1": {"quantity": 200}}),
    )

    assert "approved_inputs" not in state.model_dump()
    assert "approved_inputs" not in json.loads(state.model_dump_json())


class _Args(BaseModel):
    quantity: int


class _PriceArgs(BaseModel):
    limit_price: Decimal


def test_schema_validator_returns_json_safe_canonical_arguments() -> None:
    validator = SchemaEditableApprovalValidator({"place_paper_order": _PriceArgs})

    assert validator.validate(
        tool_name="place_paper_order",
        arguments={"limit_price": "1500.50"},
    ) == {"limit_price": "1500.50"}


class _ContextTool(InProcessTool):
    name = "place_paper_order"
    description = "test"
    args_schema = _Args

    def __init__(self) -> None:
        self.seen = None

    async def run_with_state(self, args: BaseModel, state: ChatLoopState) -> dict:
        del args, state
        return {"legacy": True}

    async def run_with_context(self, args, state, context):  # type: ignore[no-untyped-def]
        del args, state
        self.seen = context.approved_input
        return {"ok": True}


@pytest.mark.asyncio
async def test_inprocess_adapter_receives_attempt_local_approved_input() -> None:
    calls = (
        StepToolCall(id="trade-1", name="place_paper_order", arguments='{"quantity":100}'),
    )
    state = ChatLoopState(
        user_id="u",
        session_id="s",
        request_id="r",
        messages=[],
        approved_inputs=build_approved_inputs(calls, {"trade-1": {"quantity": 200}}),
    )
    tool = _ContextTool()
    adapter = ChatloopToolAdapter(tool=tool, state=state, cache=None)
    context = ExecutionContext(
        request_id="r",
        turn_id="s",
        task_id="trade-1",
        user_id="u",
        approved_input=state.approved_inputs["trade-1"],
    )

    result = await adapter.execute({"quantity": 200}, context)

    assert result.success is True
    assert tool.seen == state.approved_inputs["trade-1"]
