from pathlib import Path

import pytest

from dashboard.derive.capability_resolver import (
    load_capabilities,
    resolve_all,
    resolve_status,
)
from dashboard.derive.types import CapabilityConfig, CapabilityStatus

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_load_87_capabilities() -> None:
    """v0.9.7 ETCLOVG capability landscape — 87 项,按论文 §3-§9 子层细分。"""
    caps = load_capabilities(CONFIG_DIR / "capabilities.yaml")
    assert len(caps) == 87
    assert all(c.id.count(".") >= 1 for c in caps)


def test_file_exists_rule(tmp_path: Path) -> None:
    cfg = CapabilityConfig(
        id="t.fe",
        dimension="context",
        name_cn="x",
        name_en="x",
        derive_rule={"type": "file_exists", "path": "exists.py"},
    )
    (tmp_path / "exists.py").write_text("x")
    assert resolve_status(cfg, tmp_path) == "lit"
    cfg2 = CapabilityConfig(
        id="t.fe2",
        dimension="context",
        name_cn="x",
        name_en="x",
        derive_rule={"type": "file_exists", "path": "missing.py"},
    )
    assert resolve_status(cfg2, tmp_path) == "todo"


def test_code_grep_rule(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text("def chat(self, prompt: str, tier: Tier): pass")
    cfg = CapabilityConfig(
        id="t.cg",
        dimension="context",
        name_cn="x",
        name_en="x",
        derive_rule={"type": "code_grep", "pattern": r"tier:\s*Tier", "path_glob": "*.py"},
    )
    assert resolve_status(cfg, tmp_path) == "lit"


def test_manual_rule_returns_todo() -> None:
    cfg = CapabilityConfig(
        id="t.m",
        dimension="context",
        name_cn="x",
        name_en="x",
        derive_rule={"type": "manual"},
    )
    assert resolve_status(cfg, Path("/tmp")) == "todo"


def test_unknown_rule_raises() -> None:
    cfg = CapabilityConfig(
        id="t.u",
        dimension="context",
        name_cn="x",
        name_en="x",
        derive_rule={"type": "wat"},
    )
    with pytest.raises(ValueError):
        resolve_status(cfg, Path("/tmp"))


def test_overrides_applied() -> None:
    project_root = Path(__file__).parent.parent.parent.parent  # repo root
    caps = load_capabilities(CONFIG_DIR / "capabilities.yaml")[:3]
    overrides: dict[str, CapabilityStatus] = {caps[0].id: "wip"}
    resolved = resolve_all(caps, project_root, overrides)
    assert resolved[0].status == "wip"
    assert resolved[0].derived_status in ("lit", "todo")  # 派生原值不被擦除


def test_real_project_lit_count_anchor() -> None:
    """在真实 repo 跑全部 87 capability (ETCLOVG 7 维 + 论文子层细分),lit ≈ 42。

    新增 18 项 manual capability(按论文 §3.2.2/3.2.5/3.2.7/3.3/4.3/4.4/5.6/
    5.7/6.4/7.5/8.3/9.2/9.4/9.5/9.6/11.2/11.5/12.3)全 todo, lit 数不变。"""
    project_root = Path(__file__).parent.parent.parent.parent
    caps = load_capabilities(CONFIG_DIR / "capabilities.yaml")
    resolved = resolve_all(caps, project_root)
    lit_count = sum(1 for c in resolved if c.status == "lit")
    # 容忍 ±6(grep pattern 可能调,manual 项可能改)
    assert 36 <= lit_count <= 48, f"Lit count {lit_count} out of expected 42±6"
