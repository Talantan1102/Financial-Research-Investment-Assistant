"""Verify plan_registry correctness — 4 plan × ~4 subtask 完整, instantiate 正确."""

from __future__ import annotations

import pytest
from app.agents.plan_registry import PLAN_REGISTRY, instantiate_plan


def test_4_plan_id_complete() -> None:
    """4 plan 都在 registry."""
    assert set(PLAN_REGISTRY.keys()) == {
        "capital_preservation",
        "stable_growth",
        "balanced",
        "aggressive_growth",
    }


@pytest.mark.parametrize(
    "plan_id",
    ["capital_preservation", "stable_growth", "balanced", "aggressive_growth"],
)
def test_each_plan_has_at_least_3_subtasks(plan_id: str) -> None:
    assert len(PLAN_REGISTRY[plan_id]) >= 3  # type: ignore[index]


@pytest.mark.parametrize(
    "plan_id",
    ["capital_preservation", "stable_growth", "balanced", "aggressive_growth"],
)
def test_each_subtask_has_required_tools(plan_id: str) -> None:
    for tmpl in PLAN_REGISTRY[plan_id]:  # type: ignore[index]
        assert len(tmpl.required_tools) >= 1
        assert tmpl.description_template
        assert "{target_name}" in tmpl.description_template
        assert "{ts_code}" in tmpl.description_template


def test_instantiate_balanced_plan_for_maotai() -> None:
    subtasks = instantiate_plan("balanced", target_name="贵州茅台", ts_code="600519.SH")
    assert len(subtasks) == 4
    # description_template 应已 format
    for st in subtasks:
        assert "贵州茅台" in st.description
        assert "600519.SH" in st.description
        assert "{target_name}" not in st.description  # template 已替换
        assert "{ts_code}" not in st.description


def test_instantiate_deterministic() -> None:
    """同 input 同 output — 5 次调用结果完全一致."""
    runs = [instantiate_plan("balanced", target_name="X", ts_code="000001.SZ") for _ in range(5)]
    base = [(st.subtask_id, st.description, tuple(st.required_tools)) for st in runs[0]]
    for run in runs[1:]:
        assert [(st.subtask_id, st.description, tuple(st.required_tools)) for st in run] == base


def test_4_plan_use_at_least_8_distinct_tools() -> None:
    """覆盖度 verify — 4 plan 总共应使用至少 8 个不同 tool (13 中)."""
    used: set[str] = set()
    for templates in PLAN_REGISTRY.values():
        for tmpl in templates:
            used.update(tmpl.required_tools)
    assert len(used) >= 8


def test_capital_preservation_emphasizes_solvency() -> None:
    """capital_preservation 至少 1 subtask 用 get_balance_sheet (偿债能力)."""
    used: set[str] = set()
    for tmpl in PLAN_REGISTRY["capital_preservation"]:
        used.update(tmpl.required_tools)
    assert "get_balance_sheet" in used
    assert "get_cashflow" in used


def test_aggressive_growth_emphasizes_growth_signals() -> None:
    """aggressive_growth 至少 1 subtask 用 get_forecast / get_money_flow."""
    used: set[str] = set()
    for tmpl in PLAN_REGISTRY["aggressive_growth"]:
        used.update(tmpl.required_tools)
    assert "get_forecast" in used or "get_money_flow" in used


def test_stable_growth_emphasizes_dividend() -> None:
    used: set[str] = set()
    for tmpl in PLAN_REGISTRY["stable_growth"]:
        used.update(tmpl.required_tools)
    assert "get_dividend_history" in used
