"""路径 → 8 维主泳道 + App Shell 归类。

冲突解决:更具体的优先 (specificity = path_glob 去通配符后字符数)。
"""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
from typing import cast

import yaml

from .types import DimensionConfig, DimensionId


def load_dimensions(
    yaml_path: Path,
) -> tuple[list[DimensionConfig], list[DimensionConfig]]:
    """加载 dimensions.yaml,返回 (8 维主泳道, App Shell 6 项)。"""
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    main = [
        DimensionConfig(
            id=d["id"],
            number=d["number"],
            name_cn=d["name_cn"],
            name_en=d["name_en"],
            paths=tuple(d["paths"]),
            keywords=tuple(d.get("keywords", [])),
        )
        for d in data["dimensions"]
    ]
    app_shell = [
        DimensionConfig(
            id=d["id"],  # M2:保留 frontend/backend/auth/... 子 id
            number="09",
            name_cn=d["name_cn"],
            name_en=d["name_cn"],  # App Shell 子项无 name_en,降级用中文
            paths=tuple(d["paths"]),
        )
        for d in data["app_shell"]
    ]
    return main, app_shell


def _specificity(path_glob: str) -> int:
    """更长(去通配符后)更具体。"""
    return len(path_glob.replace("*", "").replace("?", "").replace("[", "").replace("]", ""))


def classify_path(
    path: str,
    main_dims: list[DimensionConfig],
    app_shell: list[DimensionConfig],
) -> DimensionId:
    """归类一个 forward-slash 路径到 dimension id;无命中返 'unknown'。"""
    candidates: list[tuple[int, DimensionId]] = []
    for d in main_dims:
        for glob in d.paths:
            if fnmatch(path, glob):
                # main_dims 的 id 在 yaml 内容上仍为 DimensionId 子集,运行时安全
                candidates.append((_specificity(glob), cast(DimensionId, d.id)))
    for d in app_shell:
        for glob in d.paths:
            if fnmatch(path, glob):
                candidates.append((_specificity(glob), "app_shell"))
    if not candidates:
        return "unknown"
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]
