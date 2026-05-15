"""Tests for plan_validator — 3-layer validator gate."""
from __future__ import annotations

from app.agents.plan_template import DD_PLAN_TEMPLATE
from app.agents.plan_validator import ValidationResult, validate_plan
from app.agents.schemas import ResearchPlan, Subtask


def _mk_sub(sid: str, desc: str, tools: list[str], rationale: str = "r") -> Subtask:
    return Subtask(subtask_id=sid, description=desc, required_tools=tools, rationale=rationale)


def _mk_plan(subtasks: list[Subtask]) -> ResearchPlan:
    return ResearchPlan(rationale="t", subtasks=subtasks)


def test_validate_ok_minimal_required_coverage() -> None:
    plan = _mk_plan([
        _mk_sub("s1", "财务全景: 三表", ["get_financials", "get_balance_sheet"]),
        _mk_sub("s2", "估值 — PE 分位", ["get_pe_history"]),
        _mk_sub("s3", "行业地位", ["web_search"]),
        _mk_sub("s4", "风险底线", ["get_holder_change"]),
    ])
    r = validate_plan(plan, DD_PLAN_TEMPLATE)
    assert r.ok, r.errors


def test_validate_missing_required_dim() -> None:
    plan = _mk_plan([
        _mk_sub("s1", "财务全景", ["get_financials", "get_balance_sheet"]),
        _mk_sub("s2", "估值", ["get_pe_history"]),
        _mk_sub("s3", "行业地位", ["web_search"]),
        # 缺 "风险底线"
    ])
    r = validate_plan(plan, DD_PLAN_TEMPLATE)
    assert not r.ok
    assert any("风险底线" in e for e in r.errors), r.errors


def test_validate_dim_min_tools_violated() -> None:
    """财务全景 min_tools=2, give only 1 candidate-matching tool → fail."""
    plan = _mk_plan([
        _mk_sub("s1", "财务全景", ["get_financials"]),  # only 1 of {balance,cashflow,financials}
        _mk_sub("s2", "估值", ["get_pe_history"]),
        _mk_sub("s3", "行业地位", ["web_search"]),
        _mk_sub("s4", "风险底线", ["get_holder_change"]),
    ])
    r = validate_plan(plan, DD_PLAN_TEMPLATE)
    assert not r.ok
    assert any("财务全景" in e and "< 2" in e for e in r.errors), r.errors


def test_validate_tool_not_in_palette() -> None:
    """Hallucinated tool → fail."""
    plan = _mk_plan([
        _mk_sub("s1", "财务全景", ["get_financials", "get_balance_sheet"]),
        _mk_sub("s2", "估值", ["get_pe_history", "get_fake_tool"]),
        _mk_sub("s3", "行业地位", ["web_search"]),
        _mk_sub("s4", "风险底线", ["get_holder_change"]),
    ])
    r = validate_plan(plan, DD_PLAN_TEMPLATE)
    assert not r.ok
    assert any("get_fake_tool" in e and "palette" in e for e in r.errors), r.errors


def test_validate_max_subtasks_exceeded() -> None:
    """11 subtasks > max_subtasks=10 → fail."""
    subs = [
        _mk_sub("s1", "财务全景", ["get_financials", "get_balance_sheet"]),
        _mk_sub("s2", "估值", ["get_pe_history"]),
        _mk_sub("s3", "行业地位", ["web_search"]),
        _mk_sub("s4", "风险底线", ["get_holder_change"]),
    ]
    # add 7 extra to reach 11
    for i in range(7):
        subs.append(_mk_sub(f"sx{i}", f"extra {i}", ["get_news"]))
    plan = _mk_plan(subs)
    r = validate_plan(plan, DD_PLAN_TEMPLATE)
    assert not r.ok
    assert any("too many subtasks" in e for e in r.errors), r.errors


def test_validate_per_subtask_tool_count() -> None:
    """max_tool_calls_per_subtask=3 → 4 tools in 1 subtask fails."""
    plan = _mk_plan([
        _mk_sub("s1", "财务全景", ["get_financials", "get_balance_sheet", "get_cashflow", "get_news"]),
        _mk_sub("s2", "估值", ["get_pe_history"]),
        _mk_sub("s3", "行业地位", ["web_search"]),
        _mk_sub("s4", "风险底线", ["get_holder_change"]),
    ])
    r = validate_plan(plan, DD_PLAN_TEMPLATE)
    assert not r.ok
    assert any("s1" in e and ("4 tools" in e or "> 3" in e) for e in r.errors), r.errors


def test_validate_per_subtask_duplicate_forbidden() -> None:
    """Per-subtask duplicate tool list → fail.

    Architectural decision: forbid_duplicate_calls=True means no dup
    WITHIN a single subtask's required_tools. Cross-subtask reuse OK.
    """
    plan = _mk_plan([
        _mk_sub("s1", "财务全景", ["get_financials", "get_financials"]),  # dup within
        _mk_sub("s2", "估值", ["get_pe_history"]),
        _mk_sub("s3", "行业地位", ["web_search"]),
        _mk_sub("s4", "风险底线", ["get_holder_change"]),
    ])
    r = validate_plan(plan, DD_PLAN_TEMPLATE)
    assert not r.ok
    assert any("duplicate" in e.lower() for e in r.errors), r.errors
    # New: error names the offending tool
    assert any("get_financials" in e for e in r.errors), r.errors


def test_validate_paraphrased_dim_name_fails_coverage() -> None:
    """Dim coverage uses substring match on description/rationale.

    Pins the contract that the LLM planner MUST echo dim names verbatim
    (e.g. "财务全景" must appear literally, not paraphrased as "财务概览"
    or "三表分析"). If this test fails, the validator's coverage detector
    likely loosened — confirm intent before "fixing" this test.
    """
    plan = _mk_plan([
        _mk_sub("s1", "三表分析", ["get_financials", "get_balance_sheet"]),  # paraphrase, no "财务全景"
        _mk_sub("s2", "估值", ["get_pe_history"]),
        _mk_sub("s3", "行业地位", ["web_search"]),
        _mk_sub("s4", "风险底线", ["get_holder_change"]),
    ])
    r = validate_plan(plan, DD_PLAN_TEMPLATE)
    assert not r.ok
    assert any("财务全景" in e for e in r.errors)


def test_validate_empty_subtasks_fails_all_required_dims() -> None:
    """Pin behavior for empty plan — all required dims report missing.

    Note: ResearchPlan schema enforces min_length=1 on subtasks (Task 1.3),
    so this state isn't reachable via LLM output; this test guards the
    validator's own behavior in case schema constraint is loosened.
    """
    # Construct directly via model_construct to bypass min_length validation
    # (or use plan_id + 1 dummy subtask that doesn't cover any dim)
    plan = _mk_plan([_mk_sub("dummy", "无关描述", ["get_financials", "get_balance_sheet"])])
    r = validate_plan(plan, DD_PLAN_TEMPLATE)
    assert not r.ok
    # All 4 required dims should be reported missing
    for dim_name in ("财务全景", "估值", "行业地位", "风险底线"):
        assert any(dim_name in e for e in r.errors), f"expected {dim_name} in errors: {r.errors}"


def test_validate_cross_subtask_reuse_allowed() -> None:
    """Same tool across DIFFERENT subtasks is OK (e.g. get_news in 风险 + 催化)."""
    plan = _mk_plan([
        _mk_sub("s1", "财务全景", ["get_financials", "get_balance_sheet"]),
        _mk_sub("s2", "估值", ["get_pe_history"]),
        _mk_sub("s3", "行业地位", ["web_search"]),
        _mk_sub("s4", "风险底线", ["get_holder_change", "get_news"]),
        _mk_sub("s5", "近期催化", ["get_news"]),  # reuse — should be fine
    ])
    r = validate_plan(plan, DD_PLAN_TEMPLATE)
    assert r.ok, r.errors


def test_validation_result_serializable() -> None:
    r = ValidationResult(ok=False, errors=["e1", "e2"])
    assert r.model_dump() == {"ok": False, "errors": ["e1", "e2"]}


def test_validation_result_frozen() -> None:
    """ValidationResult should be frozen for safety."""
    import pytest
    from pydantic import ValidationError
    r = ValidationResult(ok=True, errors=[])
    with pytest.raises((ValidationError, AttributeError, TypeError)):
        r.ok = False  # type: ignore[misc]
