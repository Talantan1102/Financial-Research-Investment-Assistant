"""L0 unit tests for SkillLoader.load_skill_md() — L2 layer."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from app.skills import SkillLoaderError
from app.skills.skill_loader import SKILL_MD_WARN_BYTES, SkillLoader


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    base = tmp_path / "claude_skills"
    base.mkdir()
    (base / "alpha").mkdir()
    (base / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: Alpha skill.\n---\n\n# Alpha\n\nLorem ipsum body content.\n"
    )
    return base


class TestLoadSkillMd:
    def test_returns_body_without_frontmatter(self, skills_dir: Path) -> None:
        loader = SkillLoader(skills_root=skills_dir)
        body = loader.load_skill_md("alpha")
        assert "# Alpha" in body
        assert "Lorem ipsum" in body
        assert "name: alpha" not in body
        assert "---" not in body.split("\n")[0]

    def test_unknown_skill_raises(self, skills_dir: Path) -> None:
        loader = SkillLoader(skills_root=skills_dir)
        with pytest.raises(SkillLoaderError, match="not found"):
            loader.load_skill_md("does_not_exist")

    def test_oversized_skill_md_logs_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        base = tmp_path / "claude_skills"
        (base / "huge").mkdir(parents=True)
        body = "x" * (SKILL_MD_WARN_BYTES + 1024)
        (base / "huge" / "SKILL.md").write_text(
            f"---\nname: huge\ndescription: Huge skill.\n---\n\n{body}\n"
        )
        loader = SkillLoader(skills_root=base)
        with caplog.at_level(logging.WARNING):
            _ = loader.load_skill_md("huge")
        assert any("SKILL.md size" in rec.message for rec in caplog.records)

    def test_skill_md_under_warn_threshold_no_log(
        self, skills_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        loader = SkillLoader(skills_root=skills_dir)
        with caplog.at_level(logging.WARNING):
            _ = loader.load_skill_md("alpha")
        assert not any("SKILL.md size" in rec.message for rec in caplog.records)
