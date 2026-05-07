from pathlib import Path

import pytest

from dashboard.derive.decision_extractor import (
    classify_layer,
    extract_from_memory,
    extract_from_specs,
    resolve_memory_path,
)
from dashboard.derive.path_router import load_dimensions
from dashboard.derive.types import DimensionConfig, compute_decision_id


@pytest.fixture
def main_dims() -> list[DimensionConfig]:
    yaml_path = Path(__file__).parent.parent.parent / "config" / "dimensions.yaml"
    main, _ = load_dimensions(yaml_path)
    return main


def test_extract_from_specs_basic(tmp_path: Path) -> None:
    """spec section 扫:抓 ## § X 决策 N 段。"""
    spec_file = tmp_path / "2026-05-05-v0.8.5-test-design.md"
    spec_file.write_text(
        """# Test Spec

## § 0 元信息

非决策段。

## § 2 决策一:Constrained LLM Router

**问题陈述**:prompt 漂移。
**业界 alternatives**:LangChain / Pydantic AI。

## § 3 决策二:Skills Bundle

**问题陈述**:skill 复用。
""",
        encoding="utf-8",
    )
    decisions = extract_from_specs(tmp_path)
    assert len(decisions) == 2
    titles = sorted(d.title for d in decisions)
    assert any("Constrained LLM Router" in t for t in titles)
    assert any("Skills Bundle" in t for t in titles)
    # version 从文件名 regex
    assert all(d.version == "v0.8.5" for d in decisions)


def test_extract_from_memory_frontmatter(tmp_path: Path, main_dims: list[DimensionConfig]) -> None:
    """memory 文件 frontmatter 扫:type=feedback|project 才进入。"""
    mem_a = tmp_path / "feedback_test_lesson.md"
    mem_a.write_text(
        """---
name: 测试教训
description: prompt 漂移要用 constrained schema 防御
type: feedback
---

正文内容。
""",
        encoding="utf-8",
    )

    mem_b = tmp_path / "project_v0.8.5_landed.md"
    mem_b.write_text(
        """---
name: v0.8.5 落地
description: Constrained LLM Router + Skills bundle
type: project
---
""",
        encoding="utf-8",
    )

    mem_c = tmp_path / "user_role.md"
    mem_c.write_text(
        """---
name: user role
description: senior LLM dev
type: user
---
""",
        encoding="utf-8",
    )

    decisions = extract_from_memory(tmp_path, main_dims)
    # type=user 不进入,只有 feedback + project 共 2 项
    assert len(decisions) == 2
    titles = {d.title for d in decisions}
    assert "测试教训" in titles
    assert "v0.8.5 落地" in titles
    # version derive
    versions = {d.version for d in decisions}
    assert "v0.8.5" in versions
    assert "unversioned" in versions


def test_layer_keyword_classification(main_dims: list[DimensionConfig]) -> None:
    """关键字归类:文本含 dim keywords → 命中该 dim,无命中 → META。"""
    # dimensions.yaml.06 keywords = ["Schema", "Pydantic", "retry"]
    text_06 = "Pydantic schema 验证 + retry edge"
    assert classify_layer(text_06, main_dims) == "guardrails"

    # dimensions.yaml.08 keywords = ["TierRouter", "pricing"]
    text_08 = "TierRouter 3 层选 model"
    assert classify_layer(text_08, main_dims) == "cost_routing"

    # 无 keyword → META
    text_no = "随便写点没 keyword 的"
    assert classify_layer(text_no, main_dims) == "META"


def test_decision_id_stable() -> None:
    """同 input → 同 ID(12 字 hex)。"""
    id1 = compute_decision_id("v0.8.5", "06", "Constrained Router")
    id2 = compute_decision_id("v0.8.5", "06", "Constrained Router")
    assert id1 == id2
    assert len(id1) == 12
    assert all(c in "0123456789abcdef" for c in id1)
    # 不同 input → 不同 ID
    id3 = compute_decision_id("v0.8.5", "07", "Constrained Router")
    assert id1 != id3


def test_resolve_memory_path_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """env var 优先于 auto-detect。"""
    custom = tmp_path / "custom_memory"
    custom.mkdir()
    monkeypatch.setenv("HARNESS_MEMORY_PATH", str(custom))
    assert resolve_memory_path() == custom


def test_resolve_memory_path_fallback_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """env 没设 + auto-detect 不存在 → None。"""
    monkeypatch.delenv("HARNESS_MEMORY_PATH", raising=False)
    monkeypatch.setattr(
        "dashboard.derive.decision_extractor.PROJECT_ROOT", Path("/nonexistent/path")
    )
    assert resolve_memory_path() is None


def test_extract_from_memory_skips_index_file(
    tmp_path: Path, main_dims: list[DimensionConfig]
) -> None:
    """MEMORY.md(index 文件)不进决策列表,即使它有 frontmatter。"""
    index = tmp_path / "MEMORY.md"
    index.write_text(
        """---
name: index
description: index file
type: project
---
""",
        encoding="utf-8",
    )
    real = tmp_path / "project_v1_test.md"
    real.write_text(
        """---
name: v1 test
description: real decision
type: project
---
""",
        encoding="utf-8",
    )
    decisions = extract_from_memory(tmp_path, main_dims)
    assert len(decisions) == 1
    assert decisions[0].title == "v1 test"
