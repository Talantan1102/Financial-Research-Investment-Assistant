"""SkillLoader — L1 list + L2 SKILL.md + L3a resource progressive disclosure."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from app.skills.types import (
    NestedDepthExceededError,
    ResourceTooLargeError,
    SkillLoaderError,
    SkillLoadResult,
    SkillManifest,
    SkillResource,
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

    # --- L2 ----------------------------------------------------------------

    def load_skill_md(self, name: str) -> str:
        """Return SKILL.md body (frontmatter stripped) for the given skill.

        Raises SkillLoaderError if skill missing.

        S3: emits a WARNING log if SKILL.md exceeds 30kB (soft threshold).
        """
        skill_md = self.skills_root / name / "SKILL.md"
        if not skill_md.exists():
            raise SkillLoaderError(f"skill not found: {name}")

        text = skill_md.read_text(encoding="utf-8")
        size = len(text.encode("utf-8"))
        if size > SKILL_MD_WARN_BYTES:
            log.warning(
                "SKILL.md size %d bytes exceeds soft cap %d bytes for skill %s",
                size,
                SKILL_MD_WARN_BYTES,
                name,
            )

        m = _FRONTMATTER_RE.match(text)
        if not m:
            return text
        return m.group(2)

    # --- L3a helpers -------------------------------------------------------

    @staticmethod
    def _detect_resource_refs(text: str) -> list[str]:
        """Return de-duplicated list of `resources/*` refs in markdown text.

        S4: foundation of nested-depth tracking. Resources can themselves
        contain refs (only md files in practice). Caller walks BFS up to
        depth 2.
        """
        seen: set[str] = set()
        out: list[str] = []
        for m in _RESOURCE_LINK_RE.finditer(text):
            ref = m.group(1)
            if ref not in seen:
                seen.add(ref)
                out.append(ref)
        return out

    _CONTENT_TYPE_BY_EXT: dict[str, str] = {
        ".yaml": "yaml",
        ".yml": "yaml",
        ".json": "json",
        ".md": "md",
    }

    def _load_one_resource(self, skill_name: str, relative_ref: str) -> SkillResource:
        """Read a single resource file with size + path-traversal guards (S5)."""
        if not relative_ref.startswith("resources/"):
            raise SkillLoaderError(
                f"invalid resource ref (must start with 'resources/'): {relative_ref!r}"
            )

        skill_root = (self.skills_root / skill_name).resolve()
        resources_root = (skill_root / "resources").resolve()
        target = (skill_root / relative_ref).resolve()

        try:
            target.relative_to(resources_root)
        except ValueError as e:
            raise SkillLoaderError(
                f"path traversal blocked: {relative_ref!r} escapes resources/"
            ) from e

        if not target.exists() or not target.is_file():
            raise SkillLoaderError(f"resource not found: {relative_ref}")

        ext = target.suffix.lower()
        ct = self._CONTENT_TYPE_BY_EXT.get(ext)
        if ct is None:
            raise SkillLoaderError(
                f"unsupported resource extension {ext!r} (allowed: .yaml/.yml/.json/.md)"
            )

        size = target.stat().st_size
        if size > RESOURCE_SIZE_CAP_BYTES:
            raise ResourceTooLargeError(
                f"resource {relative_ref} is {size} bytes, exceeds 50kB cap "
                f"({RESOURCE_SIZE_CAP_BYTES} bytes)"
            )

        content = target.read_text(encoding="utf-8")
        return SkillResource(
            name=target.stem,
            relative_path=relative_ref,
            content_type=ct,  # type: ignore[arg-type]
            content=content,
            size_bytes=size,
        )

    # --- L2 + L3a orchestrator ---------------------------------------------

    def load_skill(self, name: str) -> SkillLoadResult:
        """Load SKILL.md + recursively-referenced L3a resources for `name`.

        BFS walk:
        - depth 1 = SKILL.md body
        - depth 2 = resources from SKILL.md
        - depth 3 = refs inside a depth-2 .md resource — REJECTED (S4)
        """
        skill_md_body = self.load_skill_md(name)
        depth_used = 1
        resources: list[SkillResource] = []

        depth1_refs = self._detect_resource_refs(skill_md_body)
        if not depth1_refs:
            return SkillLoadResult(
                name=name,
                skill_md_content=skill_md_body,
                resources=[],
                total_size_bytes=len(skill_md_body.encode("utf-8")),
                depth_used=1,
            )

        depth_used = 2
        for ref in depth1_refs:
            r = self._load_one_resource(name, ref)
            resources.append(r)
            if r.content_type == "md":
                nested = self._detect_resource_refs(r.content)
                if nested:
                    raise NestedDepthExceededError(
                        f"depth 3 > cap {NESTED_DEPTH_CAP} at {ref!r} "
                        f"(found {len(nested)} nested ref(s) in markdown resource)"
                    )

        total = len(skill_md_body.encode("utf-8")) + sum(r.size_bytes for r in resources)
        return SkillLoadResult(
            name=name,
            skill_md_content=skill_md_body,
            resources=resources,
            total_size_bytes=total,
            depth_used=depth_used,
        )

    def load_resource(self, skill_name: str, relative_ref: str) -> SkillResource:
        """Public API: load one resource without walking SKILL.md."""
        return self._load_one_resource(skill_name, relative_ref)

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
