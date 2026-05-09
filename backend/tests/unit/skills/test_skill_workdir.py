"""L0 — skill_workdir context manager."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.skills.skill_workdir import make_skill_workdir


def test_make_skill_workdir_creates_unique_dir(tmp_path):
    with make_skill_workdir(run_id="r1", root=tmp_path) as wd:
        assert wd.exists()
        assert wd.is_dir()
        assert wd.name.startswith("r1-")
        assert wd.parent == tmp_path


def test_make_skill_workdir_isolates_concurrent_runs(tmp_path):
    with (
        make_skill_workdir(run_id="r1", root=tmp_path) as wd1,
        make_skill_workdir(run_id="r1", root=tmp_path) as wd2,
    ):
        assert wd1 != wd2


def test_make_skill_workdir_cleans_up(tmp_path):
    captured: Path
    with make_skill_workdir(run_id="r1", root=tmp_path) as wd:
        (wd / "scratch.txt").write_text("hi")
        captured = wd
    assert not captured.exists()


def test_make_skill_workdir_cleans_up_even_on_exception(tmp_path):
    captured: Path | None = None
    with pytest.raises(RuntimeError), make_skill_workdir(run_id="r1", root=tmp_path) as wd:
        captured = wd
        (wd / "scratch.txt").write_text("hi")
        raise RuntimeError("boom")
    assert captured is not None
    assert not captured.exists()


def test_make_skill_workdir_creates_root_if_missing(tmp_path):
    nonexistent = tmp_path / "deep" / "nested" / "root"
    with make_skill_workdir(run_id="r1", root=nonexistent) as wd:
        assert wd.exists()
