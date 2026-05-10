"""L0 unit tests for SkillLoader L3a — resource detection + load + depth/size guards."""

from __future__ import annotations

from pathlib import Path

from app.skills.skill_loader import SkillLoader


class TestDetectResourceRefs:
    def test_detects_yaml_link(self) -> None:
        loader = SkillLoader(skills_root=Path("/dev/null"))
        body = "See [thresholds](resources/risk_thresholds.yaml) for details."
        refs = loader._detect_resource_refs(body)
        assert refs == ["resources/risk_thresholds.yaml"]

    def test_detects_multiple_links(self) -> None:
        loader = SkillLoader(skills_root=Path("/dev/null"))
        body = (
            "Refer to [thresholds](resources/thresholds.yaml) and "
            "[examples](resources/examples.json) for context."
        )
        refs = loader._detect_resource_refs(body)
        assert sorted(refs) == sorted(["resources/thresholds.yaml", "resources/examples.json"])

    def test_detects_dotslash_prefix(self) -> None:
        loader = SkillLoader(skills_root=Path("/dev/null"))
        body = "[doc](./resources/notes.md)"
        refs = loader._detect_resource_refs(body)
        assert refs == ["resources/notes.md"]

    def test_ignores_external_links(self) -> None:
        loader = SkillLoader(skills_root=Path("/dev/null"))
        body = "See [docs](https://example.com/foo) and [api](http://x/api)."
        refs = loader._detect_resource_refs(body)
        assert refs == []

    def test_ignores_link_to_other_dirs(self) -> None:
        loader = SkillLoader(skills_root=Path("/dev/null"))
        body = "See [src](src/foo.py) or [scripts](scripts/x.py)."
        refs = loader._detect_resource_refs(body)
        assert refs == []

    def test_dedups_repeat_refs(self) -> None:
        loader = SkillLoader(skills_root=Path("/dev/null"))
        body = "[a](resources/x.yaml)\n[b](resources/x.yaml)\n[c](resources/y.json)\n"
        refs = loader._detect_resource_refs(body)
        assert sorted(refs) == ["resources/x.yaml", "resources/y.json"]


import pytest  # noqa: E402


class TestLoadOneResource:
    @pytest.fixture
    def skills_dir(self, tmp_path: Path) -> Path:
        base = tmp_path / "claude_skills"
        (base / "demo").mkdir(parents=True)
        (base / "demo" / "SKILL.md").write_text("---\nname: demo\ndescription: x\n---\n# Demo\n")
        (base / "demo" / "resources").mkdir()
        (base / "demo" / "resources" / "thresholds.yaml").write_text("pe_max: 30\npb_max: 5\n")
        (base / "demo" / "resources" / "examples.json").write_text('{"a": 1, "b": 2}\n')
        (base / "demo" / "resources" / "notes.md").write_text("# Notes\nSome content.\n")
        return base

    def test_load_yaml_resource(self, skills_dir: Path) -> None:
        loader = SkillLoader(skills_root=skills_dir)
        r = loader._load_one_resource("demo", "resources/thresholds.yaml")
        assert r.content_type == "yaml"
        assert "pe_max: 30" in r.content
        assert r.size_bytes == len(r.content.encode("utf-8"))

    def test_load_json_resource(self, skills_dir: Path) -> None:
        loader = SkillLoader(skills_root=skills_dir)
        r = loader._load_one_resource("demo", "resources/examples.json")
        assert r.content_type == "json"

    def test_load_md_resource(self, skills_dir: Path) -> None:
        loader = SkillLoader(skills_root=skills_dir)
        r = loader._load_one_resource("demo", "resources/notes.md")
        assert r.content_type == "md"

    def test_unknown_extension_raises(self, tmp_path: Path) -> None:
        base = tmp_path / "claude_skills"
        (base / "x" / "resources").mkdir(parents=True)
        (base / "x" / "resources" / "data.txt").write_text("hi")
        loader = SkillLoader(skills_root=base)
        with pytest.raises(Exception, match="unsupported"):
            loader._load_one_resource("x", "resources/data.txt")

    def test_missing_resource_raises(self, skills_dir: Path) -> None:
        loader = SkillLoader(skills_root=skills_dir)
        from app.skills import SkillLoaderError

        with pytest.raises(SkillLoaderError, match="not found"):
            loader._load_one_resource("demo", "resources/missing.yaml")

    def test_path_traversal_blocked(self, skills_dir: Path) -> None:
        loader = SkillLoader(skills_root=skills_dir)
        from app.skills import SkillLoaderError

        with pytest.raises(SkillLoaderError, match="path traversal|invalid"):
            loader._load_one_resource("demo", "resources/../SKILL.md")

    def test_oversized_resource_raises(self, tmp_path: Path) -> None:
        base = tmp_path / "claude_skills"
        (base / "x" / "resources").mkdir(parents=True)
        (base / "x" / "resources" / "big.yaml").write_text("a" * (51 * 1024))
        loader = SkillLoader(skills_root=base)
        from app.skills import ResourceTooLargeError

        with pytest.raises(ResourceTooLargeError, match="50"):
            loader._load_one_resource("x", "resources/big.yaml")

    def test_at_cap_boundary_accepted(self, tmp_path: Path) -> None:
        base = tmp_path / "claude_skills"
        (base / "x" / "resources").mkdir(parents=True)
        (base / "x" / "resources" / "exact.yaml").write_text("a" * (50 * 1024))
        loader = SkillLoader(skills_root=base)
        r = loader._load_one_resource("x", "resources/exact.yaml")
        assert r.size_bytes == 50 * 1024


class TestLoadSkillFull:
    @pytest.fixture
    def linear_skill(self, tmp_path: Path) -> Path:
        base = tmp_path / "claude_skills"
        (base / "linear" / "resources").mkdir(parents=True)
        (base / "linear" / "SKILL.md").write_text(
            "---\nname: linear\ndescription: linear demo\n---\n"
            "# Linear\n\nSee [thresholds](resources/thresholds.yaml).\n"
        )
        (base / "linear" / "resources" / "thresholds.yaml").write_text("a: 1\n")
        return base

    def test_load_skill_returns_l2_plus_l3a(self, linear_skill: Path) -> None:
        loader = SkillLoader(skills_root=linear_skill)
        result = loader.load_skill("linear")
        assert result.name == "linear"
        assert "Linear" in result.skill_md_content
        assert len(result.resources) == 1
        assert result.resources[0].name == "thresholds"
        assert result.depth_used == 2

    def test_load_skill_no_resources_depth_one(self, tmp_path: Path) -> None:
        base = tmp_path / "claude_skills"
        (base / "bare").mkdir(parents=True)
        (base / "bare" / "SKILL.md").write_text(
            "---\nname: bare\ndescription: x\n---\n# Bare\n\nNo links.\n"
        )
        loader = SkillLoader(skills_root=base)
        result = loader.load_skill("bare")
        assert result.depth_used == 1
        assert result.resources == []

    @pytest.fixture
    def nested_skill(self, tmp_path: Path) -> Path:
        base = tmp_path / "claude_skills"
        (base / "nested" / "resources").mkdir(parents=True)
        (base / "nested" / "SKILL.md").write_text(
            "---\nname: nested\ndescription: x\n---\n# Nested\n[notes](resources/notes.md)\n"
        )
        (base / "nested" / "resources" / "notes.md").write_text(
            "Notes — see [more](resources/deeper.md).\n"
        )
        (base / "nested" / "resources" / "deeper.md").write_text("# deeper\n")
        return base

    def test_load_skill_depth_3_raises(self, nested_skill: Path) -> None:
        from app.skills import NestedDepthExceededError

        loader = SkillLoader(skills_root=nested_skill)
        with pytest.raises(NestedDepthExceededError, match="depth"):
            loader.load_skill("nested")

    @pytest.fixture
    def depth2_skill(self, tmp_path: Path) -> Path:
        base = tmp_path / "claude_skills"
        (base / "d2" / "resources").mkdir(parents=True)
        (base / "d2" / "SKILL.md").write_text(
            "---\nname: d2\ndescription: x\n---\n# d2\n[notes](resources/notes.md)\n"
        )
        (base / "d2" / "resources" / "notes.md").write_text("# Notes\nNo nested refs here.\n")
        return base

    def test_load_skill_depth_2_accepted(self, depth2_skill: Path) -> None:
        loader = SkillLoader(skills_root=depth2_skill)
        result = loader.load_skill("d2")
        assert result.depth_used == 2
        assert len(result.resources) == 1
        assert result.resources[0].name == "notes"

    def test_load_skill_total_size_aggregates(self, linear_skill: Path) -> None:
        loader = SkillLoader(skills_root=linear_skill)
        result = loader.load_skill("linear")
        expected = len(result.skill_md_content.encode("utf-8")) + sum(
            r.size_bytes for r in result.resources
        )
        assert result.total_size_bytes == expected

    def test_load_skill_unknown_raises(self, linear_skill: Path) -> None:
        from app.skills import SkillLoaderError

        loader = SkillLoader(skills_root=linear_skill)
        with pytest.raises(SkillLoaderError, match="not found"):
            loader.load_skill("ghost")
