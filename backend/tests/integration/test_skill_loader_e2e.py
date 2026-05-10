"""L1 e2e — user asks "茅台风险大不大" → planner emits load_skill: risk_assessment
→ SkillLoader loads SKILL.md + risk_thresholds.yaml → ChatState.skill_context populated
→ subsequent load_resource appends.

Uses real backend/claude_skills/ directory (no mocks).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.agents.schemas import ChatState, Plan
from app.orchestration.context_node import (
    handle_resource_load_action,
    handle_skill_load_action,
)
from app.skills.skill_loader import SkillLoader


@pytest.fixture
def real_loader() -> SkillLoader:
    """Loader pointing at the real backend/claude_skills/ directory."""
    repo_root = Path(__file__).resolve().parents[2]
    return SkillLoader(skills_root=repo_root / "claude_skills")


def _make_state(plan: Plan | None = None, skill_context: dict[str, str] | None = None) -> ChatState:
    return ChatState(
        user_id="u",
        session_id="e2e-1",
        user_message="茅台 600519 风险大不大?",
        request_id="r1",
        trace_request_id="r1",
        plan=plan,
        skill_context=skill_context or {},
    )


class TestSkillLoaderE2E:
    def test_l1_list_includes_risk_assessment(self, real_loader: SkillLoader) -> None:
        manifests = real_loader.load_l1()
        names = [m.name for m in manifests]
        assert "risk_assessment" in names
        risk_m = next(m for m in manifests if m.name == "risk_assessment")
        # description references risk-related concepts
        assert "风险" in risk_m.description or "risk" in risk_m.description.lower()

    def test_load_skill_pulls_skill_md_plus_yaml_resource(self, real_loader: SkillLoader) -> None:
        result = real_loader.load_skill("risk_assessment")
        # SKILL.md content reachable via skill_md_content
        assert len(result.skill_md_content) > 100
        assert result.depth_used == 2
        assert any(r.relative_path == "resources/risk_thresholds.yaml" for r in result.resources)
        yaml_r = next(
            r for r in result.resources if r.relative_path == "resources/risk_thresholds.yaml"
        )
        assert "valuation" in yaml_r.content
        assert "score_weights" in yaml_r.content

    def test_full_chain_planner_to_state_to_responder_context(
        self, real_loader: SkillLoader
    ) -> None:
        """Round 1: load_skill → bundle in skill_context.
        Round 2: load_resource → bundle grows by 1 resource block (re-load idempotent except formatting).
        """
        # Round 1: planner emits load_skill
        plan1 = Plan(
            direct_response=False,
            tool_calls=[],
            reasoning="r",
            load_skill="risk_assessment",
        )
        state = _make_state(plan=plan1)
        assert state.skill_context == {}

        state_after_load = handle_skill_load_action(state, plan1, real_loader)

        assert "risk_assessment" in state_after_load.skill_context
        bundle = state_after_load.skill_context["risk_assessment"]
        # SKILL.md + YAML content concatenated
        assert "valuation" in bundle
        assert "score_weights" in bundle
        assert "risk_level_cuts" in bundle

        # Round 2: planner emits load_resource for the same yaml (drill)
        plan2 = Plan(
            direct_response=False,
            tool_calls=[],
            reasoning="r",
            load_resource={
                "skill": "risk_assessment",
                "ref": "resources/risk_thresholds.yaml",
            },
        )
        state_after_load = ChatState(
            user_id="u",
            session_id="e2e-1",
            user_message="x",
            request_id="r2",
            trace_request_id="r2",
            plan=plan2,
            skill_context=state_after_load.skill_context,
        )

        state_after_resource = handle_resource_load_action(state_after_load, plan2, real_loader)

        # Bundle now has 2 instances of the resource block (1 from load_skill auto-resolve, 1 from explicit load_resource).
        new_bundle = state_after_resource.skill_context["risk_assessment"]
        assert new_bundle.count("## Resource: resources/risk_thresholds.yaml") == 2

    def test_l1_block_renders_for_planner_prompt(self, real_loader: SkillLoader) -> None:
        from app.agents.chat_planner import build_skill_list_block

        manifests = real_loader.load_l1()
        block = build_skill_list_block(manifests)
        assert "risk_assessment" in block
        assert "financial_analysis" in block
        assert "market_data" in block
        assert "load_skill" in block
        assert "load_resource" in block

    def test_unloaded_resource_no_op(self, real_loader: SkillLoader) -> None:
        """load_resource before load_skill = graceful no-op."""
        plan = Plan(
            direct_response=False,
            tool_calls=[],
            reasoning="r",
            load_resource={
                "skill": "risk_assessment",
                "ref": "resources/risk_thresholds.yaml",
            },
        )
        state = _make_state(plan=plan)
        new_state = handle_resource_load_action(state, plan, real_loader)
        assert "risk_assessment" not in new_state.skill_context
