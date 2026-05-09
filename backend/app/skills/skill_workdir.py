"""Skill workdir — context-managed temp dir for L3b script execution."""

from __future__ import annotations

import contextlib
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path


@contextlib.contextmanager
def make_skill_workdir(*, run_id: str, root: Path | str) -> Iterator[Path]:
    """Create a unique workdir and clean it up on exit (success or exception)."""
    root_p = Path(root)
    root_p.mkdir(parents=True, exist_ok=True)
    suffix = uuid.uuid4().hex[:8]
    wd = root_p / f"{run_id}-{suffix}"
    wd.mkdir(parents=True, exist_ok=False)
    try:
        yield wd
    finally:
        shutil.rmtree(wd, ignore_errors=True)
