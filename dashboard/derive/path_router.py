"""路径 → ETCLOVG 7 维主泳道 + catch_all 归类。

冲突解决:更具体的优先 (specificity = path_glob 去通配符后字符数)。
未命中主泳道但命中 catch_all 返 "shell";都未命中返 "unknown"。
论文锚点: Li et al., Agent Harness Engineering: A Survey (2026), §2.3。
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
    """加载 dimensions.yaml,返回 (7 维 ETCLOVG 主泳道, catch_all 5 项)。"""
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
    catch_all = [
        DimensionConfig(
            id=d["id"],  # 保留 shell.frontend / shell.backend_router 等子 id
            number="08",  # 仅占位,catch_all 不参与主泳道编号
            name_cn=d["name_cn"],
            name_en=d["name_cn"],  # catch_all 无 name_en,降级用中文
            paths=tuple(d["paths"]),
        )
        for d in data["catch_all"]
    ]
    return main, catch_all


def _specificity(path_glob: str) -> int:
    """更长(去通配符后)更具体。"""
    return len(path_glob.replace("*", "").replace("?", "").replace("[", "").replace("]", ""))


def classify_path(
    path: str,
    main_dims: list[DimensionConfig],
    catch_all: list[DimensionConfig],
) -> DimensionId:
    """归类一个 forward-slash 路径到 dimension id;无命中返 'unknown'。

    主泳道 7 维优先;未命中主泳道但命中 catch_all 统一返 'shell'(子 id
    在 D-view 代码地图渲染时由调用方从 catch_all list 二次查询)。
    """
    candidates: list[tuple[int, DimensionId]] = []
    for d in main_dims:
        for glob in d.paths:
            if fnmatch(path, glob):
                # main_dims 的 id 在 yaml 内容上仍为 DimensionId 子集,运行时安全
                candidates.append((_specificity(glob), cast(DimensionId, d.id)))
    for d in catch_all:
        for glob in d.paths:
            if fnmatch(path, glob):
                candidates.append((_specificity(glob), "shell"))
    if not candidates:
        return "unknown"
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]
