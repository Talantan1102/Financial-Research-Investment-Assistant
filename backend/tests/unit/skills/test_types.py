"""L0 unit tests for backend/app/skills/types.py."""

from __future__ import annotations

import pytest
from app.skills.types import (
    NestedDepthExceededError,
    ResourceTooLargeError,
    SkillLoaderError,
    SkillLoadResult,
    SkillManifest,
    SkillResource,
)
from pydantic import ValidationError


class TestSkillManifest:
    def test_minimal_valid_manifest(self) -> None:
        m = SkillManifest(
            name="risk_assessment",
            description="Investment risk assessment skill.",
            path="backend/claude_skills/risk_assessment",
        )
        assert m.name == "risk_assessment"
        assert m.version == "1.0"
        assert m.tool_count == 0

    def test_name_must_be_snake_case(self) -> None:
        with pytest.raises(ValidationError):
            SkillManifest(name="Risk-Assessment", description="x", path="x")

    def test_description_max_length_512_chars(self) -> None:
        with pytest.raises(ValidationError):
            SkillManifest(name="x", description="a" * 513, path="x")

    def test_description_required_non_empty(self) -> None:
        with pytest.raises(ValidationError):
            SkillManifest(name="x", description="", path="x")


class TestSkillResource:
    def test_resource_with_yaml_content(self) -> None:
        r = SkillResource(
            name="risk_thresholds",
            relative_path="resources/risk_thresholds.yaml",
            content_type="yaml",
            content="thresholds:\n  pe: 30\n",
            size_bytes=22,
        )
        assert r.content_type == "yaml"
        assert r.size_bytes == 22

    def test_content_type_enum(self) -> None:
        with pytest.raises(ValidationError):
            SkillResource(
                name="x",
                relative_path="resources/x.exe",
                content_type="binary",
                content="",
                size_bytes=0,
            )

    def test_content_type_allows_yaml_json_md(self) -> None:
        for ct in ("yaml", "json", "md"):
            r = SkillResource(
                name="x",
                relative_path=f"resources/x.{ct}",
                content_type=ct,
                content="",
                size_bytes=0,
            )
            assert r.content_type == ct


class TestSkillLoadResult:
    def test_result_with_skill_md_only(self) -> None:
        result = SkillLoadResult(
            name="risk_assessment",
            skill_md_content="# Risk\n",
            resources=[],
            total_size_bytes=8,
            depth_used=1,
        )
        assert len(result.resources) == 0
        assert result.depth_used == 1

    def test_result_with_resources(self) -> None:
        r = SkillResource(
            name="thresholds",
            relative_path="resources/thresholds.yaml",
            content_type="yaml",
            content="x: 1\n",
            size_bytes=5,
        )
        result = SkillLoadResult(
            name="risk_assessment",
            skill_md_content="# Risk\n",
            resources=[r],
            total_size_bytes=13,
            depth_used=2,
        )
        assert len(result.resources) == 1
        assert result.depth_used == 2


class TestExceptions:
    def test_resource_too_large_inherits_skill_loader_error(self) -> None:
        e = ResourceTooLargeError("resource X.yaml is 60000 bytes (cap 51200)")
        assert isinstance(e, SkillLoaderError)
        assert "60000" in str(e)

    def test_nested_depth_exceeded_inherits(self) -> None:
        e = NestedDepthExceededError("depth 3 > cap 2 at resources/a.yaml")
        assert isinstance(e, SkillLoaderError)
