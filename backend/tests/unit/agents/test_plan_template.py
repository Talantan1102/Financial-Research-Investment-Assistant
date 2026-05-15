from app.agents.plan_template import (
    DD_PLAN_TEMPLATE,
    SAFE_DEFAULT_PLAN,
    PlanTemplate,
)
from app.agents.schemas import SubtaskTemplate, ToolName

# Ensure PlanTemplate type symbol is exported.
_ = PlanTemplate


def test_dd_template_has_4_required_dimensions():
    assert len(DD_PLAN_TEMPLATE["required_dimensions"]) == 4
    names = {d["name"] for d in DD_PLAN_TEMPLATE["required_dimensions"]}
    assert names == {"财务全景", "估值", "行业地位", "风险底线"}


def test_dd_template_has_3_optional_dimensions():
    assert len(DD_PLAN_TEMPLATE["optional_dimensions"]) == 3
    names = {d["name"] for d in DD_PLAN_TEMPLATE["optional_dimensions"]}
    assert names == {"近期催化", "资金动向", "同业对比"}


def test_dd_template_tool_palette_only_known_tools():
    known = set(ToolName.__args__)
    for tool in DD_PLAN_TEMPLATE["tool_palette"]:
        assert tool in known, f"unknown tool: {tool}"


def test_dd_template_required_dim_candidates_in_palette():
    palette = set(DD_PLAN_TEMPLATE["tool_palette"])
    for dim in DD_PLAN_TEMPLATE["required_dimensions"]:
        for tool in dim["tool_candidates"]:
            assert tool in palette, f"required dim candidate '{tool}' not in palette"


def test_dd_template_optional_dim_candidates_in_palette():
    palette = set(DD_PLAN_TEMPLATE["tool_palette"])
    for dim in DD_PLAN_TEMPLATE["optional_dimensions"]:
        for tool in dim["tool_candidates"]:
            assert tool in palette


def test_dd_template_constraints():
    c = DD_PLAN_TEMPLATE["constraints"]
    assert c["max_subtasks"] == 10
    assert c["max_tool_calls_per_subtask"] == 3
    assert c["forbid_duplicate_calls"] is True


def test_safe_default_plan_has_7_subtasks():
    assert len(SAFE_DEFAULT_PLAN) == 7


def test_safe_default_plan_uses_only_palette_tools():
    palette = set(DD_PLAN_TEMPLATE["tool_palette"])
    for tmpl in SAFE_DEFAULT_PLAN:
        for tool in tmpl.required_tools:
            assert tool in palette


def test_safe_default_plan_uses_subtask_template():
    for tmpl in SAFE_DEFAULT_PLAN:
        assert isinstance(tmpl, SubtaskTemplate)
