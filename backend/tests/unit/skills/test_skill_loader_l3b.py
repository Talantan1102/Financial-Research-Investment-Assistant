"""L0 — SkillLoader.detect_l3b_refs."""

from __future__ import annotations

import pytest
from app.skills.skill_loader import SkillLoader


@pytest.fixture
def fake_skills_root(tmp_path):
    skill = tmp_path / "claude_skills" / "demo"
    (skill / "scripts").mkdir(parents=True)
    (skill / "scripts" / "calc.py").write_text("# placeholder")
    (skill / "scripts" / "score.py").write_text("# placeholder")
    (skill / "SKILL.md").write_text(
        "---\nname: demo\ndescription: x\n---\n"
        "# demo skill\n"
        "## Available scripts\n"
        "- `scripts/calc.py` — compute X from inputs Y\n"
        "- `scripts/score.py` — score risk\n"
    )
    return tmp_path / "claude_skills"


def test_detect_l3b_refs_finds_scripts(fake_skills_root):
    loader = SkillLoader(skills_root=fake_skills_root)
    refs = loader.detect_l3b_refs("demo")
    paths = {r.script_path for r in refs}
    assert "scripts/calc.py" in paths
    assert "scripts/score.py" in paths


def test_detect_l3b_refs_extracts_descriptions(fake_skills_root):
    loader = SkillLoader(skills_root=fake_skills_root)
    refs = loader.detect_l3b_refs("demo")
    by_path = {r.script_path: r.description for r in refs}
    assert "compute X" in (by_path["scripts/calc.py"] or "")
    assert "score risk" in (by_path["scripts/score.py"] or "")


def test_detect_l3b_refs_skips_missing_files(tmp_path):
    skill = tmp_path / "claude_skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: demo\ndescription: x\n---\n"
        "## Available scripts\n- `scripts/missing.py` — describe\n"
    )
    loader = SkillLoader(skills_root=tmp_path / "claude_skills")
    refs = loader.detect_l3b_refs("demo")
    assert refs == []


def test_detect_l3b_refs_unknown_skill_returns_empty(tmp_path):
    loader = SkillLoader(skills_root=tmp_path / "claude_skills")
    assert loader.detect_l3b_refs("ghost") == []
