"""Tombstone guard — plan_registry deleted in C71 code-review fix.

C71: PlanId was only referenced by the self-declared-deprecated plan_registry.py.
Both have been removed. These tests pin the deletion invariant — any
re-introduction of plan_registry or PlanId will fail CI.

If you genuinely need the old PLAN_REGISTRY data, copy it into plan_template.py
— do NOT recreate plan_registry.py or re-add PlanId to schemas.
"""

from __future__ import annotations

import pathlib


def test_plan_registry_not_imported_in_app() -> None:
    """No app module may import the deleted plan_registry."""
    app_root = pathlib.Path(__file__).resolve().parents[3] / "app"
    offenders = []
    for py in app_root.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        if "from app.agents.plan_registry" in text or "import plan_registry" in text:
            offenders.append(str(py.relative_to(app_root)))
    assert not offenders, f"plan_registry deleted (C71) but still imported by: {offenders}"


def test_plan_registry_file_deleted() -> None:
    """Physical file must not exist — guards accidental re-creation."""  # C71
    plan_registry_path = (
        pathlib.Path(__file__).resolve().parents[3] / "app" / "agents" / "plan_registry.py"
    )
    assert not plan_registry_path.exists(), (
        "plan_registry.py was deleted in C71 but has been re-created; "
        "move the required content to plan_template.py instead"
    )


def test_plan_id_not_in_schemas() -> None:
    """PlanId Literal removed from schemas.py — import must fail."""  # C71
    import importlib

    schemas = importlib.import_module("app.agents.schemas")
    assert not hasattr(schemas, "PlanId"), (
        "PlanId was removed from schemas.py in C71 but has been re-added; "
        "InvestmentObjective covers the same domain for live callers"
    )
