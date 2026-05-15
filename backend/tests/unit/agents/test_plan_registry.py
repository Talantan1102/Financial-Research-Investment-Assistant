"""Guard test — plan_registry deprecation status.

v1.x: plan_registry.py is archive-only (no live import). Tasks 1.4
(planner rewrite) and this task verified no `from app.agents.plan_registry`
or `import plan_registry` remains in the app/ tree. This test pins that
invariant — any reintroduction will fail CI.

If you genuinely need plan_registry's old PLAN_REGISTRY data, copy what you
need into the new home (plan_template.py) — do NOT re-import from the
deprecated module.
"""
from __future__ import annotations

import pathlib


def test_plan_registry_not_imported_in_app() -> None:
    app_root = pathlib.Path(__file__).resolve().parents[3] / "app"
    offenders = []
    for py in app_root.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        if "from app.agents.plan_registry" in text or "import plan_registry" in text:
            offenders.append(str(py.relative_to(app_root)))
    assert not offenders, f"plan_registry deprecated but still imported by: {offenders}"


def test_plan_registry_module_marked_deprecated() -> None:
    """The deprecation banner must remain in the module docstring."""
    import app.agents.plan_registry as pr
    docstring = pr.__doc__ or ""
    assert "DEPRECATED" in docstring
    assert "v1.x" in docstring
