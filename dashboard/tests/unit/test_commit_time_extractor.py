"""Plan 2 Task 1 — commit-time 抽取器 unit tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from dashboard.derive.commit_time_extractor import (
    extract_cap_commit_time,
    extract_first_commit_for_paths,
)


def test_extract_first_commit_simple(tmp_path: Path) -> None:
    """模拟 subprocess git log 返回单行 ISO 时间。"""
    fake_output = "2026-04-15T10:23:00+08:00"
    with patch(
        "dashboard.derive.commit_time_extractor.subprocess.check_output",
        return_value=fake_output,
    ):
        ts = extract_first_commit_for_paths(
            ["backend/app/services/llm_service.py"], cwd=tmp_path
        )
    assert ts is not None
    assert ts.startswith("2026-04-15")


def test_extract_first_commit_no_paths_returns_none(tmp_path: Path) -> None:
    assert extract_first_commit_for_paths([], cwd=tmp_path) is None


def test_extract_first_commit_subprocess_fail(tmp_path: Path) -> None:
    with patch(
        "dashboard.derive.commit_time_extractor.subprocess.check_output",
        side_effect=subprocess.CalledProcessError(1, "git"),
    ):
        ts = extract_first_commit_for_paths(["x.py"], cwd=tmp_path)
    assert ts is None


def test_extract_cap_commit_time_code_grep_rule(tmp_path: Path) -> None:
    """code_grep / file_exists / spec_section 都有 path/path_glob,可抽 commit。"""
    # 创建实际匹配的文件以让 glob 展开非空
    (tmp_path / "backend").mkdir(parents=True)
    (tmp_path / "backend" / "x.py").write_text("x", encoding="utf-8")
    fake_output = "2026-03-01T08:00:00+00:00"
    with patch(
        "dashboard.derive.commit_time_extractor.subprocess.check_output",
        return_value=fake_output,
    ):
        rule = {"type": "code_grep", "path_glob": "backend/**/*.py", "pattern": "x"}
        ts = extract_cap_commit_time(rule, cwd=tmp_path)
    assert ts is not None
    assert "2026-03-01" in ts


def test_extract_cap_commit_time_manual_rule_returns_none(tmp_path: Path) -> None:
    """manual rule 无 path_glob → None(spec § 5.4 fallback 由调用者处理)。"""
    ts = extract_cap_commit_time({"type": "manual"}, cwd=tmp_path)
    assert ts is None


def test_glob_expansion_passes_to_git(tmp_path: Path) -> None:
    """path_glob 包含 ** 应该展开成实际 path 列表(避免 git 不支持 glob)。"""
    # 创建几个真实文件
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    (tmp_path / "b.py").write_text("x", encoding="utf-8")
    with patch(
        "dashboard.derive.commit_time_extractor.subprocess.check_output"
    ) as m:
        m.return_value = "2026-01-01T00:00:00+00:00"
        rule = {"type": "code_grep", "path_glob": "*.py", "pattern": "x"}
        extract_cap_commit_time(rule, cwd=tmp_path)
        # subprocess 调用时 args 应含展开后的 path
        called_args = m.call_args[0][0]
        assert "a.py" in called_args or any("a.py" in a for a in called_args)
