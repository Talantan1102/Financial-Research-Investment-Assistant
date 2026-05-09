"""SkillExecutor — sandboxed L3b script runner."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import platform
import resource
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Final

from app.skills.script_schemas import (
    SkillExecutionError,
    SkillExecutionResult,
    SkillScriptArgs,
    SkillScriptRef,
)
from app.skills.skill_workdir import make_skill_workdir


def _apply_rlimits(*, memory_mb: int, cpu_seconds: int):
    """Build a preexec_fn closure that caps memory + CPU in the child process.

    POSIX-only. macOS RLIMIT_AS is unreliable for malloc — fall back to
    RLIMIT_DATA there.
    """

    def _set() -> None:
        soft_mem = memory_mb * 1024 * 1024
        if platform.system() != "Darwin":
            resource.setrlimit(resource.RLIMIT_AS, (soft_mem, soft_mem))
        else:
            with contextlib.suppress(ValueError, OSError):
                resource.setrlimit(resource.RLIMIT_DATA, (soft_mem, soft_mem))

        soft_cpu = cpu_seconds
        hard_cpu = max(cpu_seconds + 5, int(cpu_seconds * 1.5))
        resource.setrlimit(resource.RLIMIT_CPU, (soft_cpu, hard_cpu))

    return _set


# Sandbox / I/O contract constants — tunable via env/Settings later.
DEFAULT_TIMEOUT_S: Final[int] = 30
MAX_TIMEOUT_S: Final[int] = 300
MAX_MEMORY_MB: Final[int] = 256
STDERR_MAX_BYTES: Final[int] = 2048

# Whitelist for the subprocess env — everything else dropped (S6).
_ENV_WHITELIST: Final[frozenset[str]] = frozenset({"PATH", "LANG", "LC_ALL", "LC_CTYPE"})


def _minimal_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k in _ENV_WHITELIST}


class SkillExecutor:
    """Sandboxed L3b script runner."""

    def __init__(
        self,
        *,
        skills_root: Path | str,
        workdir_root: Path | str,
        default_timeout_s: int = DEFAULT_TIMEOUT_S,
        max_timeout_s: int = MAX_TIMEOUT_S,
        max_memory_mb: int = MAX_MEMORY_MB,
        stderr_max_bytes: int = STDERR_MAX_BYTES,
    ) -> None:
        self._skills_root = Path(skills_root)
        self._workdir_root = Path(workdir_root)
        self._default_timeout_s = default_timeout_s
        self._max_timeout_s = max_timeout_s
        self._max_memory_mb = max_memory_mb
        self._stderr_max_bytes = stderr_max_bytes

    async def execute(
        self,
        *,
        ref: SkillScriptRef,
        args: SkillScriptArgs,
        timeout_s: int | None = None,
    ) -> SkillExecutionResult:
        timeout = min(timeout_s or self._default_timeout_s, self._max_timeout_s)
        script_full = self._skills_root / ref.skill_name / ref.script_path
        if not script_full.is_file():
            return _err_result(
                ref,
                exit_code=-1,
                err=SkillExecutionError(
                    kind="subprocess_launch_failed",
                    message=f"script not found: {script_full}",
                ),
            )

        run_id = uuid.uuid4().hex[:8]
        with make_skill_workdir(run_id=run_id, root=self._workdir_root) as wd:
            return await self._run_subprocess(ref, script_full, args, wd, timeout)

    async def _run_subprocess(
        self,
        ref: SkillScriptRef,
        script_full: Path,
        args: SkillScriptArgs,
        cwd: Path,
        timeout_s: int,
    ) -> SkillExecutionResult:
        start = time.monotonic()
        try:
            proc = subprocess.Popen(
                [sys.executable, str(script_full)],
                cwd=str(cwd),
                env=_minimal_env(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                preexec_fn=_apply_rlimits(
                    memory_mb=self._max_memory_mb,
                    cpu_seconds=timeout_s,
                ),
            )
        except OSError as exc:
            return _err_result(
                ref,
                exit_code=-1,
                err=SkillExecutionError(
                    kind="subprocess_launch_failed",
                    message=str(exc),
                ),
            )

        stdin_blob = json.dumps(args.payload).encode("utf-8")

        try:
            stdout_b, stderr_b = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: proc.communicate(input=stdin_blob, timeout=timeout_s),
            )
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            stdout_b, stderr_b = proc.communicate()
            elapsed = time.monotonic() - start
            return SkillExecutionResult(
                ok=False,
                stdout_json=None,
                stderr_text=_truncate_stderr(stderr_b, self._stderr_max_bytes),
                exit_code=-9,
                elapsed_s=elapsed,
                skill_name=ref.skill_name,
                script_path=ref.script_path,
                error=SkillExecutionError(
                    kind="timeout",
                    message=f"exceeded {timeout_s}s",
                ),
            )

        elapsed = time.monotonic() - start
        stderr_text = _truncate_stderr(stderr_b, self._stderr_max_bytes)
        stdout_text = stdout_b.decode("utf-8", errors="replace") if stdout_b else ""

        if proc.returncode != 0:
            return SkillExecutionResult(
                ok=False,
                stdout_json=None,
                stderr_text=stderr_text,
                exit_code=proc.returncode,
                elapsed_s=elapsed,
                skill_name=ref.skill_name,
                script_path=ref.script_path,
                error=SkillExecutionError(
                    kind="non_zero_exit",
                    message=f"exit code {proc.returncode}",
                ),
            )

        try:
            stdout_json = json.loads(stdout_text) if stdout_text.strip() else None
        except json.JSONDecodeError as exc:
            return SkillExecutionResult(
                ok=False,
                stdout_json=None,
                stderr_text=stderr_text,
                exit_code=proc.returncode,
                elapsed_s=elapsed,
                skill_name=ref.skill_name,
                script_path=ref.script_path,
                error=SkillExecutionError(
                    kind="stdout_invalid_json",
                    message=f"could not parse stdout as JSON: {exc}",
                ),
            )

        return SkillExecutionResult(
            ok=True,
            stdout_json=stdout_json,
            stderr_text=stderr_text,
            exit_code=proc.returncode,
            elapsed_s=elapsed,
            skill_name=ref.skill_name,
            script_path=ref.script_path,
        )


def _truncate_stderr(data: bytes, max_bytes: int) -> str:
    if not data:
        return ""
    if len(data) <= max_bytes:
        return data.decode("utf-8", errors="replace")
    return data[:max_bytes].decode("utf-8", errors="replace") + "\n...[truncated]"


def _err_result(
    ref: SkillScriptRef, *, exit_code: int, err: SkillExecutionError
) -> SkillExecutionResult:
    return SkillExecutionResult(
        ok=False,
        stdout_json=None,
        stderr_text="",
        exit_code=exit_code,
        elapsed_s=0.0,
        skill_name=ref.skill_name,
        script_path=ref.script_path,
        error=err,
    )
