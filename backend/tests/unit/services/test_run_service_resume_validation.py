from __future__ import annotations

import pytest
from app.chatloop.approval_edits import SchemaEditableApprovalValidator
from app.run_control.types import ResumeNotAllowed
from app.services.run_service import RunService
from pydantic import BaseModel, ConfigDict, Field


@pytest.mark.parametrize(
    ("pause_type", "response"),
    [
        ("input", {"approved": True}),
        ("input", {"text": 123}),
        ("approval", {"text": "yes"}),
        ("approval", {"approved": "yes"}),
        ("approval", {"approved": True, "decisions": {"call-1": True}}),
    ],
)
def test_resume_response_shape_is_bound_to_pause_type(
    pause_type: str, response: dict[str, object]
) -> None:
    with pytest.raises(ResumeNotAllowed, match="response"):
        RunService._validate_resume_response(pause_type, response)


@pytest.mark.parametrize(
    ("pause_type", "response"),
    [
        ("input", {"text": "成本价 1500"}),
        ("approval", {"approved": True}),
        ("approval", {"approved": False, "text": "不执行"}),
        ("approval", {"decisions": {"call-1": True, "call-2": False}}),
    ],
)
def test_valid_resume_response_shapes_are_accepted(
    pause_type: str, response: dict[str, object]
) -> None:
    RunService._validate_resume_response(pause_type, response)


class _TradeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: int = Field(strict=True, gt=0)


def _editable_service() -> RunService:
    return RunService(
        None,  # type: ignore[arg-type]
        editable_approval_validator=SchemaEditableApprovalValidator(
            {"place_paper_order": _TradeArgs}
        ),
    )


def _pause(*, editable: tuple[str, ...] = ("trade-1",)) -> object:
    return type(
        "Pause",
        (),
        {
            "request_payload": {
                "tool_calls": [
                    {
                        "id": "trade-1",
                        "name": "place_paper_order",
                        "arguments": '{"quantity":100}',
                    }
                ],
                "editable_tool_call_ids": list(editable),
            },
            "continuation_payload": {
                "body": {
                    "pending_action": {
                        "pending_tool_calls": [
                            {
                                "id": "trade-1",
                                "name": "place_paper_order",
                                "arguments": '{"quantity":100}',
                            }
                        ]
                    }
                }
            },
        },
    )()


def test_edit_validation_rejects_unknown_noneditable_and_invalid_schema() -> None:
    service = _editable_service()

    for pause, edited in (
        (_pause(), {"other": {"quantity": 200}}),
        (_pause(editable=()), {"trade-1": {"quantity": 200}}),
        (_pause(), {"trade-1": {"quantity": 0}}),
    ):
        with pytest.raises(ResumeNotAllowed, match="invalid edited arguments"):
            service._validate_approval_edits(pause, edited)  # type: ignore[arg-type]


def test_edit_validation_returns_complete_schema_normalized_arguments() -> None:
    service = _editable_service()

    assert service._validate_approval_edits(
        _pause(),  # type: ignore[arg-type]
        {"trade-1": {"quantity": 200}},
    ) == {"trade-1": {"quantity": 200}}
