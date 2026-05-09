"""L0 unit tests for ChatPlanner skill list injection in system prompt."""

from __future__ import annotations

from app.agents.chat_planner import build_skill_list_block
from app.skills import SkillManifest


class TestBuildSkillListBlock:
    def test_empty_list_returns_empty_string(self) -> None:
        assert build_skill_list_block([]) == ""

    def test_single_skill(self) -> None:
        m = SkillManifest(
            name="risk_assessment",
            description="Investment risk assessment.",
            path="x",
        )
        out = build_skill_list_block([m])
        assert "risk_assessment" in out
        assert "Investment risk assessment." in out
        assert "## Available Skills" in out

    def test_multiple_skills_sorted_by_name(self) -> None:
        skills = [
            SkillManifest(name="zeta", description="Z.", path="x"),
            SkillManifest(name="alpha", description="A.", path="x"),
            SkillManifest(name="mu", description="M.", path="x"),
        ]
        out = build_skill_list_block(skills)
        assert out.index("alpha") < out.index("mu") < out.index("zeta")

    def test_each_skill_on_separate_line_block(self) -> None:
        skills = [
            SkillManifest(name="a", description="aa", path="x"),
            SkillManifest(name="b", description="bb", path="x"),
        ]
        out = build_skill_list_block(skills)
        assert "- **a**:" in out
        assert "- **b**:" in out

    def test_action_protocol_described(self) -> None:
        m = SkillManifest(name="x", description="x.", path="x")
        out = build_skill_list_block([m])
        assert "load_skill" in out
        assert "load_resource" in out


class TestPlannerSkillActionFields:
    def test_plan_has_load_skill_field(self) -> None:
        from app.agents.schemas import Plan

        p = Plan(direct_response=True, tool_calls=[], reasoning="r", load_skill="risk_assessment")
        assert p.load_skill == "risk_assessment"

    def test_plan_has_load_resource_field(self) -> None:
        from app.agents.schemas import Plan

        p = Plan(
            direct_response=True,
            tool_calls=[],
            reasoning="r",
            load_resource={"skill": "risk_assessment", "ref": "resources/foo.yaml"},
        )
        assert p.load_resource is not None
        assert p.load_resource["skill"] == "risk_assessment"

    def test_plan_load_fields_default_none(self) -> None:
        from app.agents.schemas import Plan

        p = Plan(direct_response=True, tool_calls=[], reasoning="r")
        assert p.load_skill is None
        assert p.load_resource is None


class TestChatStateSkillContext:
    def test_skill_context_default_empty(self) -> None:
        from app.agents.schemas import ChatState

        s = ChatState(
            user_id="u",
            session_id="s",
            user_message="x",
            request_id="r",
            trace_request_id="r",
        )
        assert s.skill_context == {}

    def test_skill_context_accepts_str_values(self) -> None:
        from app.agents.schemas import ChatState

        s = ChatState(
            user_id="u",
            session_id="s",
            user_message="x",
            request_id="r",
            trace_request_id="r",
            skill_context={"risk_assessment": "# Risk\n..."},
        )
        assert s.skill_context["risk_assessment"].startswith("# Risk")
