"""Validation tests for terminal chat outcomes."""

import pytest
from app.chatloop.outcomes import ActionRequiredOutcome
from pydantic import ValidationError


def valid_outcome(**overrides: object) -> ActionRequiredOutcome:
    values: dict[str, object] = {
        "action_type": "apply_market_permission",
        "action_url": "/market-permissions/star/apply",
        "action_label": "申请科创板权限",
        "resume_hint": "申请完成后回来继续下单。",
        "intent_summary": "买入中芯国际 100 股。",
    }
    values.update(overrides)
    return ActionRequiredOutcome(**values)


def test_action_required_accepts_internal_navigation_only() -> None:
    outcome = valid_outcome()

    assert outcome.code == "action_required"
    assert outcome.action_url == "/market-permissions/star/apply"


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/x",
        "//evil.example/x",
        "javascript:alert(1)",
        "market-permissions/star/apply",
    ],
)
def test_action_required_rejects_external_or_active_urls(url: str) -> None:
    with pytest.raises(ValidationError):
        valid_outcome(action_url=url)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("action_type", "Apply_market_permission"),
        ("action_type", "apply-market-permission"),
        ("action_type", "a" * 65),
        ("action_url", "/" + "a" * 512),
        ("action_label", "a" * 81),
        ("resume_hint", "a" * 241),
        ("intent_summary", "a" * 501),
    ],
)
def test_action_required_validates_field_shapes_and_lengths(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        valid_outcome(**{field: value})


@pytest.mark.parametrize(
    "field", ["action_type", "action_url", "action_label", "resume_hint", "intent_summary"]
)
def test_action_required_rejects_empty_required_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        valid_outcome(**{field: ""})


def test_action_required_is_frozen_and_forbids_extra_fields() -> None:
    outcome = valid_outcome()

    with pytest.raises(ValidationError):
        ActionRequiredOutcome(**outcome.model_dump(), unexpected="value")
    with pytest.raises(ValidationError):
        outcome.action_label = "继续"
