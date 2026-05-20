"""catch_all mini stat — 数 5 项各命中多少文件。

> Plan 1 仅改 docstring 与参数名;公开函数名 `compute_app_shell_stat`
> 保留到 Plan 3 一起改(避免 server.py 调用方破坏)。
"""

from __future__ import annotations

from glob import glob
from pathlib import Path

from .types import AppShellItem, DimensionConfig


def compute_app_shell_stat(
    project_root: Path,
    catch_all: list[DimensionConfig],
) -> list[AppShellItem]:
    """对 catch_all 5 项,各自跑 glob 数文件,返回 AppShellItem 列表。

    数文件不数目录(`Path.is_file()` 过滤)。
    """
    out: list[AppShellItem] = []
    for d in catch_all:
        count = 0
        for glob_pat in d.paths:
            for fp in glob(str(project_root / glob_pat), recursive=True):
                if Path(fp).is_file():
                    count += 1
        out.append(AppShellItem(id=d.id, name_cn=d.name_cn, file_count=count))
    return out
