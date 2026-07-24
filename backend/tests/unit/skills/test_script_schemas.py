"""L0 — script_schemas Pydantic types."""

from __future__ import annotations

import pytest
from app.skills.script_schemas import (
    SkillExecutionError,
    SkillExecutionResult,
    SkillScriptArgs,
    SkillScriptRef,
)
from pydantic import ValidationError


def test_skill_script_ref_minimal():
    ref = SkillScriptRef(skill_name="financial_analysis", script_path="scripts/calculate_dcf.py")
    assert ref.skill_name == "financial_analysis"
    assert ref.script_path == "scripts/calculate_dcf.py"
    assert ref.description is None


def test_skill_script_ref_rejects_path_traversal():
    with pytest.raises(ValidationError):
        SkillScriptRef(skill_name="x", script_path="../etc/passwd")
    with pytest.raises(ValidationError):
        SkillScriptRef(skill_name="x", script_path="/abs/path.py")
    with pytest.raises(ValidationError):
        SkillScriptRef(skill_name="x", script_path="scripts/../../leak.py")


def test_skill_script_ref_requires_scripts_prefix():
    with pytest.raises(ValidationError):
        SkillScriptRef(skill_name="x", script_path="utils/helper.py")


def test_skill_script_args_arbitrary_json():
    args = SkillScriptArgs(payload={"financials": {"revenue": 1000}, "wacc": 0.08})
    assert args.payload["wacc"] == 0.08


def test_skill_execution_result_success():
    r = SkillExecutionResult(
        ok=True,
        stdout_json={"enterprise_value": 12000.0},
        stderr_text="",
        exit_code=0,
        elapsed_s=2.4,
        skill_name="financial_analysis",
        script_path="scripts/calculate_dcf.py",
    )
    assert r.ok is True
    assert r.error is None


def test_skill_execution_result_failure_carries_error():
    err = SkillExecutionError(kind="timeout", message="exceeded 30s")
    r = SkillExecutionResult(
        ok=False,
        stdout_json=None,
        stderr_text="...truncated",
        exit_code=-9,
        elapsed_s=30.1,
        skill_name="x",
        script_path="scripts/y.py",
        error=err,
    )
    assert r.ok is False
    assert r.error.kind == "timeout"


def test_skill_execution_error_kind_enum():
    valid_kinds = {
        "timeout",
        "memory_limit",
        "cpu_limit",
        "non_zero_exit",
        "stdout_invalid_json",
        "safety_scan_rejected",
        "sandbox_setup_failed",
        "subprocess_launch_failed",
        "stderr_overflow",
    }
    err = SkillExecutionError(kind="timeout", message="x")
    assert err.kind in valid_kinds
    with pytest.raises(ValidationError):
        SkillExecutionError(kind="not_a_real_kind", message="x")


def test_skill_execution_result_invariant_ok_implies_zero_exit_and_json():
    with pytest.raises(ValidationError):
        SkillExecutionResult(
            ok=True,
            stdout_json=None,
            stderr_text="",
            exit_code=0,
            elapsed_s=1.0,
            skill_name="x",
            script_path="scripts/y.py",
        )
    with pytest.raises(ValidationError):
        SkillExecutionResult(
            ok=True,
            stdout_json={"a": 1},
            stderr_text="",
            exit_code=2,
            elapsed_s=1.0,
            skill_name="x",
            script_path="scripts/y.py",
        )


def test_skill_execution_result_invariant_failure_must_have_error():
    with pytest.raises(ValidationError):
        SkillExecutionResult(
            ok=False,
            stdout_json=None,
            stderr_text="",
            exit_code=1,
            elapsed_s=1.0,
            skill_name="x",
            script_path="scripts/y.py",
            error=None,
        )
