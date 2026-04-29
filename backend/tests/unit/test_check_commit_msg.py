"""Test commit-msg layer validator (per spec §13 rule 3)."""

import subprocess
import sys
import tempfile
from pathlib import Path

VALIDATOR = Path(__file__).resolve().parents[3] / "scripts" / "check_commit_msg.py"


def run_validator(commit_msg: str) -> subprocess.CompletedProcess:
    """Invoke the validator script with commit_msg via temp file path arg.

    Pre-commit's commit-msg hook passes the commit message file path as $1.
    We simulate by writing to a temp file.
    """
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt") as f:
        f.write(commit_msg)
        tmp_path = f.name
    return subprocess.run(
        [sys.executable, str(VALIDATOR), tmp_path],
        capture_output=True,
        text=True,
    )


# --- Cases that must PASS validation ---


def test_accepts_impl_layer():
    msg = "fix(planner): handle empty tool_calls\n\n原因 layer: impl"
    result = run_validator(msg)
    assert result.returncode == 0, f"stderr: {result.stderr}"


def test_accepts_plan_layer():
    msg = "fix(eval): add missing factuality check\n\n原因 layer: plan"
    result = run_validator(msg)
    assert result.returncode == 0


def test_accepts_spec_layer():
    msg = "fix(arch): adjust agent dispatch protocol\n\n原因 layer: spec"
    result = run_validator(msg)
    assert result.returncode == 0


def test_accepts_non_fix_commit_without_layer():
    """Non-fix commits (feat/chore/docs/test/refactor) don't need layer marker."""
    msg = "feat(planner): add new dispatch strategy"
    result = run_validator(msg)
    assert result.returncode == 0


def test_accepts_chore_without_layer():
    msg = "chore(deps): bump openai to 1.40"
    result = run_validator(msg)
    assert result.returncode == 0


# --- Cases that must FAIL validation ---


def test_rejects_fix_without_layer():
    msg = "fix(planner): handle empty tool_calls"
    result = run_validator(msg)
    assert result.returncode != 0
    assert "原因 layer" in result.stdout + result.stderr


def test_rejects_fix_with_invalid_layer():
    msg = "fix(planner): handle empty tool_calls\n\n原因 layer: bug"
    result = run_validator(msg)
    assert result.returncode != 0
    assert "原因 layer" in result.stdout + result.stderr


def test_rejects_fix_with_layer_typo():
    msg = "fix(planner): handle empty tool_calls\n\n原因layer: impl"  # missing space
    result = run_validator(msg)
    assert result.returncode != 0
