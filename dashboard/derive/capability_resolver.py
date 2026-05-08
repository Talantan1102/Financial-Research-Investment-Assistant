"""5 类 derive_rule 解析:code_grep / file_exists / spec_section / memory_frontmatter / manual。"""

from __future__ import annotations

import re
from glob import glob
from pathlib import Path
from typing import Any

import yaml

from .types import Capability, CapabilityConfig, CapabilityStatus, DimensionId


def load_capabilities(yaml_path: Path) -> list[CapabilityConfig]:
    """加载 capabilities.yaml,返回 62 个 CapabilityConfig(id 形如 '<dim>.<cap>')。"""
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    out: list[CapabilityConfig] = []
    for dim in data["dimensions"]:
        dim_id: DimensionId = dim["id"]
        for cap in dim["capabilities"]:
            out.append(
                CapabilityConfig(
                    id=f"{dim_id}.{cap['id']}",
                    dimension=dim_id,
                    name_cn=cap["name_cn"],
                    name_en=cap.get("name_en", cap["name_cn"]),
                    derive_rule=cap["derive_rule"],
                )
            )
    return out


def resolve_status(capability: CapabilityConfig, project_root: Path) -> CapabilityStatus:
    """按 derive_rule.type 分发,返回 lit/wip/todo。manual 默认 todo。"""
    rule: dict[str, Any] = capability.derive_rule
    rtype = rule["type"]
    if rtype == "manual":
        return "todo"
    if rtype == "file_exists":
        return "lit" if (project_root / rule["path"]).exists() else "todo"
    if rtype == "code_grep":
        pattern = re.compile(rule["pattern"])
        for fp in glob(str(project_root / rule["path_glob"]), recursive=True):
            try:
                if pattern.search(Path(fp).read_text(encoding="utf-8", errors="ignore")):
                    return "lit"
            except (OSError, UnicodeDecodeError):
                continue
        return "todo"
    if rtype == "spec_section":
        spec_pat = re.compile(rule["section_pattern"])
        for fp in glob(str(project_root / rule["path"]), recursive=True):
            try:
                if spec_pat.search(Path(fp).read_text(encoding="utf-8", errors="ignore")):
                    return "lit"
            except (OSError, UnicodeDecodeError):
                continue
        return "todo"
    if rtype == "memory_frontmatter":
        version_re = re.compile(
            r"^version:\s*" + re.escape(str(rule.get("version", ""))), re.MULTILINE
        )
        for fp in glob(str(project_root / rule["path"]), recursive=True):
            try:
                content = Path(fp).read_text(encoding="utf-8", errors="ignore")
            except (OSError, UnicodeDecodeError):
                continue
            if version_re.search(content):
                return "lit"
        return "todo"
    raise ValueError(f"Unknown derive_rule type: {rtype}")


def resolve_all(
    capabilities: list[CapabilityConfig],
    project_root: Path,
    overrides: dict[str, CapabilityStatus] | None = None,
) -> list[Capability]:
    """resolve all + apply overrides;保留 derived_status 原值便于审计。"""
    overrides = overrides or {}
    out: list[Capability] = []
    for c in capabilities:
        derived = resolve_status(c, project_root)
        final = overrides.get(c.id, derived)
        out.append(
            Capability(
                id=c.id,
                dimension=c.dimension,
                name_cn=c.name_cn,
                name_en=c.name_en,
                status=final,
                derived_status=derived,
            )
        )
    return out
