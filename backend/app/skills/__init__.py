"""Skill progressive-disclosure loader package.

Each subpackage groups domain knowledge (JSON/YAML lookup tables) with pure
Python helper functions that the LLM router can invoke through the constrained
tool surface.

Exposes:
- SkillManifest: L1 metadata (name, description, version, path)
- SkillResource: L3a resource (yaml/json/md content + size)
- SkillLoadResult: aggregate of L2 + L3a resources for one skill
- Errors: SkillLoaderError, ResourceTooLargeError, NestedDepthExceededError
"""

from __future__ import annotations

from app.skills.types import (
    NestedDepthExceededError,
    ResourceTooLargeError,
    SkillLoaderError,
    SkillLoadResult,
    SkillManifest,
    SkillResource,
)

__all__ = [
    "NestedDepthExceededError",
    "ResourceTooLargeError",
    "SkillLoaderError",
    "SkillLoadResult",
    "SkillManifest",
    "SkillResource",
]
