from __future__ import annotations

import pytest
from app.run_control.types import ResumeNotAllowed
from app.services.run_service import RunService


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
