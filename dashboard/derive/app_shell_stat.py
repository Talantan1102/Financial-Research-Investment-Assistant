"""App Shell 第 9 行 mini stat — 数 6 项各命中多少文件。"""

from __future__ import annotations

from glob import glob
from pathlib import Path

from .types import AppShellItem, DimensionConfig


def compute_app_shell_stat(
    project_root: Path,
    app_shell: list[DimensionConfig],
) -> list[AppShellItem]:
    """对 app_shell 6 项,各自跑 glob 数文件,返回 AppShellItem 列表。

    数文件不数目录(`Path.is_file()` 过滤)。
    """
    out: list[AppShellItem] = []
    for d in app_shell:
        count = 0
        for glob_pat in d.paths:
            for fp in glob(str(project_root / glob_pat), recursive=True):
                if Path(fp).is_file():
                    count += 1
        out.append(AppShellItem(id=d.id, name_cn=d.name_cn, file_count=count))
    return out
