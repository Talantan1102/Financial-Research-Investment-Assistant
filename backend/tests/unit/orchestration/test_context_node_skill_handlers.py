"""L0 tests for context_node load_skill / load_resource action handling."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.agents.schemas import ChatState, Plan
from app.orchestration.context_node import (
    handle_resource_load_action,
    handle_skill_load_action,
)
from app.skills.skill_loader import SkillLoader


def _make_state(skill_context: dict[str, str] | None = None) -> ChatState:
    return ChatState(
        user_id="u",
        session_id="s",
        user_message="x",
        request_id="r",
        trace_request_id="r",
        skill_context=skill_context or {},
    )


def _empty_plan() -> Plan:
    return Plan(direct_response=True, tool_calls=[], reasoning="r")


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    base = tmp_path / "claude_skills"
    (base / "demo" / "resources").mkdir(parents=True)
    (base / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: x\n---\n# Demo\n\n[t](resources/t.yaml)\n"
    )
    (base / "demo" / "resources" / "t.yaml").write_text("threshold: 30\n")
    return base


@pytest.fixture
def loader(skills_dir: Path) -> SkillLoader:
    return SkillLoader(skills_root=skills_dir)


class TestHandleLoadSkill:
    def test_load_skill_populates_skill_context(self, loader: SkillLoader) -> None:
        state = _make_state()
        plan = Plan(direct_response=False, tool_calls=[], reasoning="r", load_skill="demo")
        new_state = handle_skill_load_action(state, plan, loader)
        assert "demo" in new_state.skill_context
        bundle = new_state.skill_context["demo"]
        assert "# Demo" in bundle
        assert "threshold: 30" in bundle

    def test_load_skill_unknown_skill_returns_state_unchanged(self, loader: SkillLoader) -> None:
        state = _make_state()
        plan = Plan(direct_response=False, tool_calls=[], reasoning="r", load_skill="ghost")
        new_state = handle_skill_load_action(state, plan, loader)
        assert "ghost" not in new_state.skill_context

    def test_load_skill_idempotent(self, loader: SkillLoader) -> None:
        state = _make_state()
        plan = Plan(direct_response=False, tool_calls=[], reasoning="r", load_skill="demo")
        s1 = handle_skill_load_action(state, plan, loader)
        s2 = handle_skill_load_action(s1, plan, loader)
        assert s2.skill_context == s1.skill_context

    def test_no_load_skill_field_no_op(self, loader: SkillLoader) -> None:
        state = _make_state()
        plan = _empty_plan()  # load_skill is None
        new_state = handle_skill_load_action(state, plan, loader)
        assert new_state.skill_context == {}


class TestHandleLoadResource:
    def test_load_resource_appends_to_existing_skill_context(self, loader: SkillLoader) -> None:
        state = _make_state(skill_context={"demo": "# Demo\n\nBody only.\n"})
        plan = Plan(
            direct_response=False,
            tool_calls=[],
            reasoning="r",
            load_resource={"skill": "demo", "ref": "resources/t.yaml"},
        )
        new_state = handle_resource_load_action(state, plan, loader)
        bundle = new_state.skill_context["demo"]
        assert "Body only." in bundle
        assert "threshold: 30" in bundle

    def test_load_resource_unknown_skill_returns_unchanged(self, loader: SkillLoader) -> None:
        state = _make_state()
        plan = Plan(
            direct_response=False,
            tool_calls=[],
            reasoning="r",
            load_resource={"skill": "ghost", "ref": "resources/x.yaml"},
        )
        new_state = handle_resource_load_action(state, plan, loader)
        assert "ghost" not in new_state.skill_context

    def test_load_resource_oversized_returns_unchanged(self, tmp_path: Path) -> None:
        base = tmp_path / "claude_skills"
        (base / "x" / "resources").mkdir(parents=True)
        (base / "x" / "SKILL.md").write_text("---\nname: x\ndescription: x\n---\n# X\n")
        (base / "x" / "resources" / "huge.yaml").write_text("a" * (51 * 1024))
        loader = SkillLoader(skills_root=base)

        state = _make_state(skill_context={"x": "# X\n"})
        plan = Plan(
            direct_response=False,
            tool_calls=[],
            reasoning="r",
            load_resource={"skill": "x", "ref": "resources/huge.yaml"},
        )
        new_state = handle_resource_load_action(state, plan, loader)
        assert "huge.yaml" not in new_state.skill_context["x"]
