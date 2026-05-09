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
