from app.agents.plan_template import (
    DD_PLAN_TEMPLATE,
    SAFE_DEFAULT_PLAN,
    PlanTemplate,
)
from app.agents.schemas import SubtaskTemplate, ToolName


def test_plan_template_typeddict_keys():
    """PlanTemplate TypedDict shape — guards future refactors."""
    keys = set(PlanTemplate.__annotations__.keys())
    assert keys == {"required_dimensions", "optional_dimensions", "tool_palette", "constraints"}


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


def test_min_tools_not_greater_than_candidates_count():
    """Sanity: min_tools <= len(tool_candidates) for every dim."""
    for dim in DD_PLAN_TEMPLATE["required_dimensions"]:
        assert dim["min_tools"] <= len(dim["tool_candidates"]), (
            f"dim '{dim['name']}' has min_tools={dim['min_tools']} "
            f"> {len(dim['tool_candidates'])} candidates — unsatisfiable"
        )
    for dim in DD_PLAN_TEMPLATE["optional_dimensions"]:
        assert dim["min_tools"] <= len(dim["tool_candidates"])


def test_palette_has_no_dead_entries():
    """Every palette tool should be reachable via at least one dim
    candidate OR appear in SAFE_DEFAULT_PLAN. Dead palette entries are
    surface area without a path to use."""
    palette = set(DD_PLAN_TEMPLATE["tool_palette"])
    used_by_dims: set[str] = set()
    for dim in DD_PLAN_TEMPLATE["required_dimensions"] + DD_PLAN_TEMPLATE["optional_dimensions"]:
        used_by_dims.update(dim["tool_candidates"])
    used_by_safe: set[str] = set()
    for tmpl in SAFE_DEFAULT_PLAN:
        used_by_safe.update(tmpl.required_tools)
    reachable = used_by_dims | used_by_safe
    dead = palette - reachable
    assert not dead, f"palette has dead entries: {dead}"


def test_safe_default_plan_self_validates_against_template():
    """SAFE_DEFAULT_PLAN must satisfy DD_PLAN_TEMPLATE's own constraints
    — it's the fallback when validator retry exhausts, so if it itself
    fails the contract, fallback is broken.

    Checks:
    1. covers all required dims (each dim's name appears in some
       subtask description) with ≥ min_tools from candidates
    2. len(subtasks) ≤ max_subtasks
    3. each subtask len(required_tools) ≤ max_tool_calls_per_subtask
    4. per-subtask no duplicate tools (forbid_duplicate_calls semantic)
    5. all tools in palette
    """
    constraints = DD_PLAN_TEMPLATE["constraints"]
    palette = set(DD_PLAN_TEMPLATE["tool_palette"])

    # 1. required dim coverage
    for dim in DD_PLAN_TEMPLATE["required_dimensions"]:
        dim_subtasks = [t for t in SAFE_DEFAULT_PLAN if dim["name"] in t.description_template]
        assert dim_subtasks, f"SAFE_DEFAULT missing dim '{dim['name']}'"
        candidates = set(dim["tool_candidates"])
        used = set()
        for t in dim_subtasks:
            used.update(set(t.required_tools) & candidates)
        assert len(used) >= dim["min_tools"], (
            f"SAFE_DEFAULT dim '{dim['name']}' has {len(used)} "
            f"candidate tools, needs ≥ {dim['min_tools']}"
        )

    # 2. max_subtasks
    assert len(SAFE_DEFAULT_PLAN) <= constraints["max_subtasks"]

    # 3. max_tool_calls_per_subtask
    for t in SAFE_DEFAULT_PLAN:
        assert len(t.required_tools) <= constraints["max_tool_calls_per_subtask"]

    # 4. per-subtask no dup (forbid_duplicate_calls semantic)
    if constraints["forbid_duplicate_calls"]:
        for t in SAFE_DEFAULT_PLAN:
            assert len(set(t.required_tools)) == len(t.required_tools), (
                f"SAFE_DEFAULT subtask '{t.description_template[:40]}...' "
                f"has duplicate tools: {t.required_tools}"
            )

    # 5. all tools in palette
    for t in SAFE_DEFAULT_PLAN:
        for tool in t.required_tools:
            assert tool in palette
