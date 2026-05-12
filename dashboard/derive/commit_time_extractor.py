"""从 git log 抽取 capability 命中文件的首个 commit 时间。spec § 5.4。"""

from __future__ import annotations

import logging
import subprocess
from glob import glob
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def extract_first_commit_for_paths(paths: list[str], *, cwd: Path) -> str | None:
    """对一组 path 跑 git log --diff-filter=A,取最早的 commit ISO 时间。

    spec § 5.4:cap 的"诞生时间"。
    paths 已展开实际文件路径(不接受 glob)。
    """
    if not paths:
        return None
    try:
        out = subprocess.check_output(
            [
                "git",
                "log",
                "--diff-filter=A",  # added
                "--reverse",
                "--format=%aI",
                "--",
                *paths,
            ],
            cwd=str(cwd),
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    first_line = out.strip().split("\n", 1)[0] if out.strip() else ""
    return first_line or None


def extract_cap_commit_time(rule: dict[str, Any], *, cwd: Path) -> str | None:
    """对单个 cap 的 derive_rule 抽 commit time。

    支持 rule.type in {file_exists, code_grep, spec_section, memory_frontmatter}。
    manual rule 返回 None — 调用者用 DeepCard.prefill_at fallback(spec § 5.4)。
    """
    rtype = rule.get("type")
    if rtype == "manual":
        return None
    path_field = "path_glob" if rtype == "code_grep" else "path"
    glob_pat = rule.get(path_field)
    if not glob_pat:
        return None
    expanded = sorted(glob(str(cwd / glob_pat), recursive=True))
    if not expanded:
        return None
    # 转 relative,git 友好
    rel = [str(Path(p).relative_to(cwd)) for p in expanded]
    return extract_first_commit_for_paths(rel, cwd=cwd)
