"""Pydantic types for SkillLoader (L1 / L2 / L3a layers).

S2 (描述工程) caps `description` at 512 chars to keep the ChatPlanner
system prompt bounded — at 7 skills × ~300 chars avg, the L1 block is
~2.1kB (~500 tokens) sustainable across 10+ planner turns.

S5 (L3a size cap) enforced by SkillLoader (not at type level) since it's
a load-time invariant. Type carries `size_bytes` so callers can verify.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class SkillLoaderError(Exception):
    """Base for all SkillLoader-raised exceptions."""


class ResourceTooLargeError(SkillLoaderError):
    """Raised when an L3a resource exceeds the 50kB cap (S5)."""


class NestedDepthExceededError(SkillLoaderError):
    """Raised when nested resource refs exceed depth 2 (S4)."""


class SkillManifest(BaseModel):
    """L1 skill metadata — fits in ChatPlanner system prompt."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=512)
    path: str = Field(min_length=1)
    version: str = "1.0"
    tool_count: int = 0

    @field_validator("name")
    @classmethod
    def _name_snake_case(cls, v: str) -> str:
        if not _SNAKE_CASE_RE.match(v):
            raise ValueError(
                f"skill name must be snake_case (lowercase, digits, underscores), got: {v!r}"
            )
        return v


class SkillResource(BaseModel):
    """L3a resource content + metadata."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    content_type: Literal["yaml", "json", "md"]
    content: str
    size_bytes: int = Field(ge=0)


class SkillLoadResult(BaseModel):
    """Result of `SkillLoader.load_skill(name)` — L2 + recursively-resolved L3a."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    skill_md_content: str
    resources: list[SkillResource] = Field(default_factory=list)
    total_size_bytes: int = Field(ge=0)
    depth_used: int = Field(ge=1, le=2)
