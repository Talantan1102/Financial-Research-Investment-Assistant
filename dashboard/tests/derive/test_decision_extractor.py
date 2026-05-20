from pathlib import Path

import pytest

from dashboard.derive.decision_extractor import (
    _spec_version,
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
    # ETCLOVG 07 governance keywords = ["Schema", "Pydantic", "auth", "guardrail"]
    text_g = "Pydantic schema 验证 + auth"
    assert classify_layer(text_g, main_dims) == "governance"

    # ETCLOVG 05 observability keywords = ["TraceService", "TierRouter", "pricing", "monitoring"]
    text_o = "TierRouter 3 层选 model"
    assert classify_layer(text_o, main_dims) == "observability"

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


def test_spec_version_regex_filename_shapes() -> None:
    """SPEC_VERSION_RE 正确匹配 4 种文件名 shape。

    Critical 1 修复:date 后允许任何前缀(如 harness-board-)再到 version token。
    """
    assert _spec_version("2026-05-05-v0.8.5-constrained-router-design.md") == "v0.8.5"
    assert _spec_version("2026-05-07-harness-board-m2-design.md") == "m2"
    assert _spec_version("2026-05-07-harness-board-m3-design.md") == "m3"
    # 无 version token → unknown
    assert _spec_version("2026-05-07-harness-board-design.md") == "unknown"


def test_extract_from_memory_skips_non_dict_frontmatter(
    tmp_path: Path, main_dims: list[DimensionConfig]
) -> None:
    """malformed frontmatter(scalar / list)应跳过,不 crash。

    Critical 2 修复:yaml.safe_load 可返 str/list/dict/None;非 dict 跳过防 AttributeError。
    """
    # scalar frontmatter
    f1 = tmp_path / "feedback_scalar.md"
    f1.write_text("---\nhello world\n---\n\n正文\n", encoding="utf-8")
    # list frontmatter
    f2 = tmp_path / "feedback_list.md"
    f2.write_text("---\n- item1\n- item2\n---\n\n正文\n", encoding="utf-8")
    # 正常 dict frontmatter
    f3 = tmp_path / "feedback_ok.md"
    f3.write_text(
        """---
name: 正常决策
description: 测试
type: feedback
---
""",
        encoding="utf-8",
    )
    decisions = extract_from_memory(tmp_path, main_dims)
    # malformed 跳过,只 1 项正常决策
    assert len(decisions) == 1
    assert decisions[0].title == "正常决策"


def test_extract_all_dedup_and_sort(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """extract_all:spec + memory 合并,同 id 取 spec,日期倒序。

    Important 3 补回:spec § 14.1 承诺的 extract_all 直测。
    用 monkeypatch PROJECT_ROOT 注入 tmp_path,把 specs/memory/dashboard config
    都搬到 tmp_path 下,验证 dedup + memory_dir 注入分支。
    """
    import dashboard.derive.decision_extractor as ext

    # 构造 tmp_path 下的目录结构(对应 extract_all 用的 PROJECT_ROOT 子路径)
    real_specs_dir = tmp_path / "docs" / "superpowers" / "specs"
    real_specs_dir.mkdir(parents=True)
    config_dir = tmp_path / "dashboard" / "config"
    config_dir.mkdir(parents=True)
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()

    # 复制真实 dimensions.yaml(extract_all 内部要 load)
    real_config = Path(__file__).parent.parent.parent / "config" / "dimensions.yaml"
    (config_dir / "dimensions.yaml").write_text(
        real_config.read_text(encoding="utf-8"), encoding="utf-8"
    )

    # spec 决策 A:title=Foo, version=v1, layer 由 classify_layer 决定(没 keyword → META)
    (real_specs_dir / "2026-05-05-v1-test.md").write_text(
        "## § 1 决策一:Foo\n\n问题陈述。\n", encoding="utf-8"
    )
    # spec 决策 B:title=Bar
    (real_specs_dir / "2026-05-04-v1-other.md").write_text(
        "## § 1 决策一:Bar\n\n问题陈述。\n", encoding="utf-8"
    )

    # memory 同 id 决策(version=v1, layer=META, title=Foo → 同 id) → 应被 dedup
    (memory_dir / "project_v1_landed.md").write_text(
        """---
name: Foo
description: dup
type: project
---
""",
        encoding="utf-8",
    )
    # memory 不重决策(unversioned + 不同 title)
    (memory_dir / "feedback_lesson.md").write_text(
        """---
name: Lesson Learned
description: 教训
type: feedback
---
""",
        encoding="utf-8",
    )

    # monkeypatch PROJECT_ROOT 让 extract_all 从 tmp_path 解析 specs / config
    monkeypatch.setattr(ext, "PROJECT_ROOT", tmp_path)
    # 通过 env 注入 memory_dir(resolve_memory_path env 优先)
    monkeypatch.setenv("HARNESS_MEMORY_PATH", str(memory_dir))

    decisions = ext.extract_all()
    titles = [d.title for d in decisions]

    # spec(Foo, Bar)+ memory 不重(Lesson Learned) = 3 项;memory Foo 被 dedup
    assert len(decisions) == 3, f"got {len(decisions)} {titles}"
    assert "Foo" in titles
    assert "Bar" in titles
    assert "Lesson Learned" in titles
    # Foo 只出现一次(memory 重复被 dedup)
    assert titles.count("Foo") == 1
    # 日期倒序:date desc(string sort 也 OK,因为 ISO date 字符串可比较)
    dates = [d.date for d in decisions]
    assert dates == sorted(dates, reverse=True), f"not sorted desc: {dates}"
