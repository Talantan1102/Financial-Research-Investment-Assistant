"""L0 — GoldenCase schema + JSONL loader."""

from pathlib import Path

import pytest
from app.services.eval_models import GoldenCase, load_golden_jsonl
from pydantic import ValidationError

GOLDEN_PATH = Path("backend/tests/fixtures/eval/golden_set_v0.jsonl")


def test_load_starter_set() -> None:
    cases = load_golden_jsonl(GOLDEN_PATH)
    assert len(cases) >= 3
    for c in cases:
        assert c.case_id
        assert c.user_input
        assert c.expected_behavior is not None
        assert c.metadata.get("added_at")


def test_case_minimal() -> None:
    c = GoldenCase(
        case_id="x",
        category="single_tool_call",
        user_input="hi",
        expected_behavior={"response_must_contain": ["ok"]},
        metadata={"added_by": "init", "added_at": "2026-04-30", "tags": ["chat"]},
    )
    assert c.category == "single_tool_call"


def test_invalid_category_rejected() -> None:
    with pytest.raises(ValidationError):
        GoldenCase(
            case_id="x",
            category="invented_category",  # type: ignore[arg-type]
            user_input="hi",
            expected_behavior={},
            metadata={},
        )
