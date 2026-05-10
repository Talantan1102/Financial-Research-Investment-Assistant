"""L0 unit tests for SkillLoader.load_l1()."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.skills.skill_loader import SkillLoader


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    base = tmp_path / "claude_skills"
    base.mkdir()
    (base / "skill_a").mkdir()
    (base / "skill_a" / "SKILL.md").write_text(
        '---\nname: skill_a\ndescription: |\n  Skill A — does X.\nversion: "1.0"\ntool_count: 3\n---\n\n# Skill A\n'
    )
    (base / "skill_b").mkdir()
    (base / "skill_b" / "SKILL.md").write_text(
        "---\nname: skill_b\ndescription: Skill B — does Y.\n---\n\n# Skill B\n"
    )
    (base / "skill_c").mkdir()
    (base / "skill_c" / "SKILL.md").write_text(
        "---\nname: skill_c\ndescription: Skill C — does Z.\n---\n\n# Skill C\n"
    )
    (base / "skill_broken").mkdir()
    (base / "skill_broken" / "SKILL.md").write_text("# No frontmatter here\n")
    (base / "scaffolding").mkdir()
    return base


class TestSkillLoaderL1:
    def test_load_l1_returns_three_valid_skills(self, skills_dir: Path) -> None:
        loader = SkillLoader(skills_root=skills_dir)
        manifests = loader.load_l1()
        names = sorted(m.name for m in manifests)
        assert names == ["skill_a", "skill_b", "skill_c"]

    def test_load_l1_skips_broken_skill(self, skills_dir: Path) -> None:
        loader = SkillLoader(skills_root=skills_dir)
        manifests = loader.load_l1()
        assert "skill_broken" not in [m.name for m in manifests]

    def test_load_l1_skips_dir_without_skill_md(self, skills_dir: Path) -> None:
        loader = SkillLoader(skills_root=skills_dir)
        manifests = loader.load_l1()
        assert "scaffolding" not in [m.name for m in manifests]

    def test_load_l1_parses_version_and_tool_count(self, skills_dir: Path) -> None:
        loader = SkillLoader(skills_root=skills_dir)
        manifests = {m.name: m for m in loader.load_l1()}
        assert manifests["skill_a"].version == "1.0"
        assert manifests["skill_a"].tool_count == 3

    def test_load_l1_defaults_for_missing_optional_fields(self, skills_dir: Path) -> None:
        loader = SkillLoader(skills_root=skills_dir)
        manifests = {m.name: m for m in loader.load_l1()}
        assert manifests["skill_b"].version == "1.0"
        assert manifests["skill_b"].tool_count == 0

    def test_load_l1_strips_pipe_block_in_description(self, skills_dir: Path) -> None:
        loader = SkillLoader(skills_root=skills_dir)
        manifests = {m.name: m for m in loader.load_l1()}
        assert "Skill A" in manifests["skill_a"].description

    def test_load_l1_returns_empty_if_skills_root_missing(self, tmp_path: Path) -> None:
        loader = SkillLoader(skills_root=tmp_path / "does_not_exist")
        assert loader.load_l1() == []

    def test_load_l1_against_real_repo_skills(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        real = repo_root / "claude_skills"
        if not real.exists():
            pytest.skip("real claude_skills/ not present")
        loader = SkillLoader(skills_root=real)
        manifests = loader.load_l1()
        names = sorted(m.name for m in manifests)
        assert "risk_assessment" in names
        assert "financial_analysis" in names
        assert len(names) >= 7
