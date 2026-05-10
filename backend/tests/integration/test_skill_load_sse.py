"""L1 smoke: skill_load_node populates skill_context.

Note: SSE writer emission only fires when run inside a real graph stream
context (via langgraph.config.get_stream_writer). For unit tests we just
verify the state update; full SSE integration is in Plan 5 cassettes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.agents.schemas import ChatState, Plan
from app.orchestration.chat_graph import resource_load_node, skill_load_node
from app.skills.skill_loader import SkillLoader


@pytest.fixture
def loader(tmp_path: Path) -> SkillLoader:
    base = tmp_path / "claude_skills"
    (base / "demo" / "resources").mkdir(parents=True)
    (base / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: x\n---\n# Demo\n[t](resources/t.yaml)\n"
    )
    (base / "demo" / "resources" / "t.yaml").write_text("a: 1\n")
    return SkillLoader(skills_root=base)


def _make_state(plan: Plan, skill_context: dict[str, str] | None = None) -> ChatState:
    return ChatState(
        user_id="u",
        session_id="s",
        user_message="x",
        request_id="r",
        trace_request_id="r",
        plan=plan,
        skill_context=skill_context or {},
    )


@pytest.mark.asyncio
async def test_skill_load_node_populates_context(loader: SkillLoader) -> None:
    plan = Plan(direct_response=False, tool_calls=[], reasoning="r", load_skill="demo")
    state = _make_state(plan)
    result = await skill_load_node(state, loader=loader)
    assert "demo" in result["skill_context"]
    assert "# Demo" in result["skill_context"]["demo"]
    assert "a: 1" in result["skill_context"]["demo"]
    # Plan cleared so planner re-evaluates
    assert result["plan"] is None


@pytest.mark.asyncio
async def test_resource_load_node_appends_to_context(loader: SkillLoader) -> None:
    plan = Plan(
        direct_response=False,
        tool_calls=[],
        reasoning="r",
        load_resource={"skill": "demo", "ref": "resources/t.yaml"},
    )
    state = _make_state(plan, skill_context={"demo": "# Demo\nBody.\n"})
    result = await resource_load_node(state, loader=loader)
    assert "Body." in result["skill_context"]["demo"]
    assert "a: 1" in result["skill_context"]["demo"]
    assert result["plan"] is None
