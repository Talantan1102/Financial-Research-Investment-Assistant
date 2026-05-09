"""SkillLoader — L1 list + L2 SKILL.md + L3a resource progressive disclosure."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from app.skills.types import (
    SkillLoaderError,
    SkillManifest,
)

log = logging.getLogger(__name__)

RESOURCE_SIZE_CAP_BYTES = 50 * 1024
SKILL_MD_WARN_BYTES = 30 * 1024
NESTED_DEPTH_CAP = 2

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
_RESOURCE_LINK_RE = re.compile(r"\[[^\]]*\]\((?:\.\/)?(resources\/[^)\s]+)\)")


class SkillLoader:
    """Filesystem-backed skill metadata + content loader."""

    def __init__(self, skills_root: Path) -> None:
        self.skills_root = skills_root

    def load_l1(self) -> list[SkillManifest]:
        """Scan skills_root/<name>/SKILL.md and return frontmatter manifests."""
        if not self.skills_root.exists() or not self.skills_root.is_dir():
            return []

        out: list[SkillManifest] = []
        for child in sorted(self.skills_root.iterdir()):
            if not child.is_dir():
                continue
            skill_md = child / "SKILL.md"
            if not skill_md.exists():
                continue
            try:
                manifest = self._parse_frontmatter(child.name, skill_md)
            except SkillLoaderError as e:
                log.warning("skipping skill %s: %s", child.name, e)
                continue
            out.append(manifest)
        return out

    def _parse_frontmatter(self, dir_name: str, skill_md: Path) -> SkillManifest:
        text = skill_md.read_text(encoding="utf-8")
        m = _FRONTMATTER_RE.match(text)
        if not m:
            raise SkillLoaderError(f"no YAML frontmatter in {skill_md}")
        try:
            meta = yaml.safe_load(m.group(1))
        except yaml.YAMLError as e:
            raise SkillLoaderError(f"invalid YAML frontmatter in {skill_md}: {e}") from e
        if not isinstance(meta, dict):
            raise SkillLoaderError(f"frontmatter not a mapping in {skill_md}")

        name = meta.get("name", dir_name)
        description = (meta.get("description") or "").strip()
        if not description:
            raise SkillLoaderError(f"empty description in {skill_md}")

        return SkillManifest(
            name=name,
            description=description,
            path=str(skill_md.parent),
            version=str(meta.get("version", "1.0")),
            tool_count=int(meta.get("tool_count", 0)),
        )
