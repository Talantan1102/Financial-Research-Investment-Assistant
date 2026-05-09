"""Pydantic types for the SkillExecutor I/O contract (S7)."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

ErrorKind = Literal[
    "timeout",
    "memory_limit",
    "cpu_limit",
    "non_zero_exit",
    "stdout_invalid_json",
    "safety_scan_rejected",
    "subprocess_launch_failed",
    "stderr_overflow",
]


class SkillScriptRef(BaseModel):
    """A reference to a script discovered inside a skill's directory."""

    skill_name: str
    script_path: str
    description: str | None = None

    @field_validator("script_path")
    @classmethod
    def _validate_path(cls, v: str) -> str:
        p = PurePosixPath(v)
        if p.is_absolute():
            raise ValueError(f"script_path must be relative; got {v!r}")
        parts = p.parts
        if not parts or parts[0] != "scripts":
            raise ValueError(f"script_path must start with 'scripts/'; got {v!r}")
        if any(part == ".." for part in parts):
            raise ValueError(f"script_path may not contain '..'; got {v!r}")
        return v


class SkillScriptArgs(BaseModel):
    """Arbitrary JSON payload sent to the script via stdin."""

    payload: dict[str, Any] = Field(default_factory=dict)


class SkillExecutionError(BaseModel):
    """Error categorization surfaced through SSE and into the LLM prompt."""

    kind: ErrorKind
    message: str


class SkillExecutionResult(BaseModel):
    """Outcome of one SkillExecutor.execute() call."""

    ok: bool
    stdout_json: dict[str, Any] | None
    stderr_text: str
    exit_code: int
    elapsed_s: float
    skill_name: str
    script_path: str
    error: SkillExecutionError | None = None
