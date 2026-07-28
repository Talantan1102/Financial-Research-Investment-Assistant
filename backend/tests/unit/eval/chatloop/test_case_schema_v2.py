"""Versioned conversational business-case schema contract tests."""

from __future__ import annotations

import re
from typing import Any

import eval.chatloop.case_schema as case_schema
import pytest
from eval.chatloop.case_schema import ConversationCase, SuiteType
from pydantic import BaseModel, ValidationError


def minimal_case_dict() -> dict[str, Any]:
    """Return the smallest representative catalog case accepted by schema v1."""
    return {
        "schema_version": 1,
        "case_id": "B1-001",
        "title_zh": "查询公告时不得写入账户状态",
        "task_type": "公开信息查询",
        "risk_level": "低风险",
        "user_goal": "查询最近公告",
        "user_messages": ["这家公司最近有什么公告？"],
        "initial_state": {
            "execution_mode": "direct",
            "actors": {"requester": {"role": "creator"}},
            "axes": {"E1": "普通投资者"},
            "business_state": {},
        },
        "hidden_facts": {"announcement_count": 1},
        "available_tools": ["search_announcements"],
        "fault_injection": [],
        "applicable_policies": [],
        "acceptable_outcomes": [],
        "required_assertions": [],
        "forbidden_outcomes": [],
        "expected_state_changes": [],
        "answer_requirements": [],
        "allowed_variations": [],
        "graders": [],
        "partial_credit": [],
        "violation_caps": {},
        "evidence": {
            "transcript": True,
            "tool_ledger": True,
            "database_before_after": True,
            "versions": True,
        },
    }


def test_case_requires_hidden_facts() -> None:
    raw = minimal_case_dict()
    raw.pop("hidden_facts")

    with pytest.raises(ValidationError, match="hidden_facts"):
        ConversationCase.model_validate(raw)


def test_risk_level_is_descriptive_and_cap_is_separate() -> None:
    raw = minimal_case_dict()
    raw["risk_level"] = "C1"

    with pytest.raises(ValidationError, match="risk_level"):
        ConversationCase.model_validate(raw)


def test_new_catalog_case_has_capability_trial_defaults_and_null_results() -> None:
    case = ConversationCase.model_validate(minimal_case_dict())

    assert case.suite_type == SuiteType.CAPABILITY
    assert case.model_dump(mode="json")["suite_type"] == "Capability"
    assert case.trial_count == 1
    assert case.trial_status is None
    assert case.task_pass is None
    assert case.task_score is None
    assert case.failure_reason is None


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("trial_status", "valid"),
        ("task_pass", True),
        ("task_score", 100),
        ("failure_reason", "unexpected write"),
    ],
)
def test_catalog_result_fields_reject_non_null_input(field_name: str, value: object) -> None:
    raw = minimal_case_dict()
    raw[field_name] = value

    with pytest.raises(ValidationError, match=field_name):
        ConversationCase.model_validate(raw)


def test_hidden_facts_schema_description_is_exact() -> None:
    schema = ConversationCase.model_json_schema()

    assert (
        schema["properties"]["hidden_facts"]["description"]
        == "评估器知道但不会直接告诉 Agent 的标准事实"
    )


def test_every_exported_model_field_has_a_chinese_schema_description() -> None:
    missing_or_non_chinese: list[str] = []

    for public_name in case_schema.__all__:
        exported = getattr(case_schema, public_name)
        if not isinstance(exported, type) or not issubclass(exported, BaseModel):
            continue
        properties = exported.model_json_schema().get("properties", {})
        for field_name in exported.model_fields:
            description = properties.get(field_name, {}).get("description", "")
            if not description.strip() or re.search(r"[\u4e00-\u9fff]", description) is None:
                missing_or_non_chinese.append(f"{public_name}.{field_name}")

    assert missing_or_non_chinese == []


def test_all_exported_models_forbid_unknown_fields() -> None:
    non_strict_models = []

    for public_name in case_schema.__all__:
        exported = getattr(case_schema, public_name)
        if (
            isinstance(exported, type)
            and issubclass(exported, BaseModel)
            and exported.model_config.get("extra") != "forbid"
        ):
            non_strict_models.append(public_name)

    assert non_strict_models == []


def test_environment_axes_reject_unknown_axis() -> None:
    raw = minimal_case_dict()
    raw["initial_state"]["axes"] = {"E15": "未定义维度"}

    with pytest.raises(ValidationError, match="E15"):
        ConversationCase.model_validate(raw)
