"""SkillExecutor — sandboxed L3b script runner."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import importlib
import json
import os
import platform
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Final

from app.skills.script_schemas import (
    SkillExecutionError,
    SkillExecutionResult,
    SkillScriptArgs,
    SkillScriptRef,
)
from app.skills.skill_workdir import make_skill_workdir

_resource = importlib.import_module("resource") if os.name == "posix" else None
_WINDOWS_GATE_TOKEN = b"CODEX_SKILL_JOB_READY\n"
_WINDOWS_GATE_BOOTSTRAP = """
import runpy
import sys

if sys.stdin.buffer.readline() != b"CODEX_SKILL_JOB_READY\\n":
    raise SystemExit(97)
sys.argv = [sys.argv[1]]
runpy.run_path(sys.argv[0], run_name="__main__")
"""


class _WindowsJob:
    def __init__(self, handle: Any, module: Any, memory_limit_bytes: int) -> None:
        self._handle = handle
        self._module = module
        self._memory_limit_bytes = memory_limit_bytes
        self._closed = False

    def memory_limit_hit(self, stderr: bytes) -> bool:
        if b"MemoryError" in stderr:
            return True
        try:
            info = self._module.QueryInformationJobObject(
                self._handle,
                self._module.JobObjectExtendedLimitInformation,
            )
            peak = int(info.get("PeakProcessMemoryUsed", 0))
        except Exception:  # pragma: no cover - defensive query after process exit
            return False
        return peak >= int(self._memory_limit_bytes * 0.9)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._handle.Close()


def _create_windows_job(
    proc: subprocess.Popen[bytes],
    *,
    memory_mb: int,
) -> _WindowsJob:
    """Bind a gated child to a memory-capped kill-on-close Job Object."""
    win32job = importlib.import_module("win32job")
    job = win32job.CreateJobObject(None, "")
    try:
        info = win32job.QueryInformationJobObject(
            job,
            win32job.JobObjectExtendedLimitInformation,
        )
        basic = info["BasicLimitInformation"]
        basic["LimitFlags"] = int(basic["LimitFlags"]) | int(
            win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY
        ) | int(win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
        memory_limit_bytes = memory_mb * 1024 * 1024
        info["ProcessMemoryLimit"] = memory_limit_bytes
        win32job.SetInformationJobObject(
            job,
            win32job.JobObjectExtendedLimitInformation,
            info,
        )
        win32job.AssignProcessToJobObject(job, proc._handle)  # type: ignore[attr-defined]
    except Exception:
        job.Close()
        raise
    return _WindowsJob(job, win32job, memory_limit_bytes)


def _apply_rlimits(*, memory_mb: int, cpu_seconds: int):
    """Build a preexec_fn closure that caps memory + CPU in the child process.

    Return ``None`` where ``preexec_fn`` and the POSIX resource module are not
    available. macOS RLIMIT_AS is unreliable for malloc, so use RLIMIT_DATA.
    """
    if _resource is None:
        return None

    def _set() -> None:
        soft_mem = memory_mb * 1024 * 1024
        if platform.system() != "Darwin":
            _resource.setrlimit(_resource.RLIMIT_AS, (soft_mem, soft_mem))
        else:
            with contextlib.suppress(ValueError, OSError):
                _resource.setrlimit(_resource.RLIMIT_DATA, (soft_mem, soft_mem))

        soft_cpu = cpu_seconds
        hard_cpu = max(cpu_seconds + 5, int(cpu_seconds * 1.5))
        _resource.setrlimit(_resource.RLIMIT_CPU, (soft_cpu, hard_cpu))

    return _set


def _terminate_process_tree(proc: subprocess.Popen[bytes]) -> None:
    if os.name == "posix":
        with contextlib.suppress(ProcessLookupError):
            posix_os: Any = os
            posix_signal: Any = signal
            posix_os.killpg(posix_os.getpgid(proc.pid), posix_signal.SIGKILL)
        return
    # taskkill is the Windows equivalent of killing the process group/tree.
    # Fall back to Popen.kill() if it is unavailable or the process survives.
    with contextlib.suppress(OSError):
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            check=False,
            capture_output=True,
        )
    if proc.poll() is None:
        proc.kill()


# Sandbox / I/O contract constants — tunable via env/Settings later.
DEFAULT_TIMEOUT_S: Final[int] = 30
MAX_TIMEOUT_S: Final[int] = 300
MAX_MEMORY_MB: Final[int] = 256
STDERR_MAX_BYTES: Final[int] = 2048

# Whitelist for the subprocess env — everything else dropped (S6).
_ENV_WHITELIST: Final[frozenset[str]] = frozenset({"PATH", "LANG", "LC_ALL", "LC_CTYPE"})

# 强制单线程 BLAS/OpenMP —— numpy/pandas/plotly 的 OpenBLAS 默认按 CPU 核数起线程,
# 每线程预留一块内存 arena,在 256MB RLIMIT_AS 下直接 OOM("OpenBLAS error: Memory
# allocation still failed")。锁成单线程既守住内存上限又让数值结果确定性可复现。
# 对纯计算技能脚本(DCF 等)无副作用;代码解释器(run_python)靠它才能在沙箱里跑通。
_SANDBOX_THREAD_ENV: Final[dict[str, str]] = {
    "OPENBLAS_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}


def _minimal_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in _ENV_WHITELIST}
    env.update(_SANDBOX_THREAD_ENV)
    return env


# 代码解释器(run_python)的可信 wrapper(spec § 3.2)。execute_source 把用户码写进
# user_code.py,把本 wrapper 写进 interp.py 跑。wrapper 做四件事:
#   1. 设默认 plotly 模板 'ios' —— 用户建的图自动套统一风格(固定画图风格);
#   2. 把 data 注入命名空间 —— 用户码直接用 `data` 变量(不用读 stdin);
#   3. 捕获用户 print 调试输出 —— 不污染 stdout(否则破坏契约 JSON);
#   4. 跑完从命名空间抓 fig/figures/result,序列化成契约 JSON;三重兜底见 spec § 3.3。
# wrapper 本身是可信代码(不经 AST 扫描),故可用 exec/open;用户码仍被 scan 禁掉这些。
# __IOS_B64__ / __DATA_B64__ 由 execute_source base64 注入(base64 纯 ASCII,免一切引号坑)。
_WRAPPER_SRC: Final[str] = """\
import sys, io, json, base64

_IOS_LAYOUT = json.loads(base64.b64decode("__IOS_B64__").decode("utf-8"))
_DATA = json.loads(base64.b64decode("__DATA_B64__").decode("utf-8"))

# 1. 套 iOS 默认模板(plotly 缺失则跳过,纯计算仍可跑)
try:
    import plotly.io as _pio
    import plotly.graph_objects as _go
    _pio.templates["ios"] = _go.layout.Template(layout=_IOS_LAYOUT)
    _pio.templates.default = "ios"
except Exception:
    pass

# 2. data 注入 + 3. 捕获用户 stdout
_ns = {"data": _DATA}
_buf = io.StringIO()
_real = sys.stdout
sys.stdout = _buf
try:
    with open("user_code.py", "r", encoding="utf-8") as _f:
        _src = _f.read()
    exec(compile(_src, "user_code.py", "exec"), _ns)
finally:
    sys.stdout = _real


def _figd(f):
    if isinstance(f, dict):
        return f
    if hasattr(f, "to_dict"):
        return f.to_dict()
    return None


# 4. 抓 fig/figures/result
_figs = _ns.get("figures")
if _figs is None and "fig" in _ns:
    _figs = [_ns["fig"]]
_result = _ns.get("result")

# 三重兜底:命名空间没图 → 解析被吞 stdout 里最后一个含 figures 的合法 JSON(旧式 print 契约)
if not _figs:
    for _line in reversed(_buf.getvalue().splitlines()):
        _line = _line.strip()
        if not _line.startswith("{"):
            continue
        try:
            _obj = json.loads(_line)
        except Exception:
            continue
        if isinstance(_obj, dict) and _obj.get("figures"):
            _figs = _obj.get("figures")
            if _result is None:
                _result = _obj.get("result")
            break

_out = []
for _f in (_figs or []):
    _d = _figd(_f)
    if _d is not None:
        _out.append(_d)

print(json.dumps({"result": _result, "figures": _out, "stdout": _buf.getvalue()[:500]},
                 default=str, ensure_ascii=False))
"""


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

        # S9 — static safety scan before launching subprocess.
        try:
            source = script_full.read_text()
            from app.skills.skill_safety import SafetyScanError, scan_script_safety  # noqa: PLC0415

            scan_script_safety(source)
        except SafetyScanError as exc:
            return _err_result(
                ref,
                exit_code=-1,
                err=SkillExecutionError(
                    kind="safety_scan_rejected",
                    message=str(exc),
                ),
            )
        except OSError as exc:
            return _err_result(
                ref,
                exit_code=-1,
                err=SkillExecutionError(
                    kind="subprocess_launch_failed",
                    message=f"could not read script: {exc}",
                ),
            )

        run_id = uuid.uuid4().hex[:8]
        with make_skill_workdir(run_id=run_id, root=self._workdir_root) as wd:
            return await self._run_subprocess(ref, script_full, args, wd, timeout)

    async def execute_source(
        self,
        *,
        source: str,
        payload: dict[str, Any],
        timeout_s: int | None = None,
    ) -> SkillExecutionResult:
        """执行 LLM 当场写的内联源码(代码解释器 run_python 用)。

        wrapper 模式(spec § 3):scan 用户码 → 写 user_code.py → 写可信 wrapper(interp.py)
        → 跑 wrapper。wrapper 自动:套 iOS plotly 主题 / 注入 data 变量 / 捕获用户 print /
        从命名空间抓 fig|figures|result 序列化(三重兜底)。模型不用记 print(JSON) 契约。
        沙箱(scan_script_safety / rlimit / 断网 env / workdir / 超时 SIGKILL)全复用。
        """
        from app.skills.plotly_theme import ios_template_layout  # noqa: PLC0415
        from app.skills.skill_safety import SafetyScanError, scan_script_safety  # noqa: PLC0415

        timeout = min(timeout_s or self._default_timeout_s, self._max_timeout_s)
        # 合成 ref —— execute_source 不读磁盘脚本,ref 仅用于结果的 skill_name/script_path
        # 标识字段(SkillScriptRef 校验 script_path 必须以 'scripts/' 开头)。
        ref = SkillScriptRef(skill_name="_interpreter", script_path="scripts/interp.py")

        # 只扫**用户码**(open/subprocess/os.popen… 仍禁);wrapper 是可信代码不扫。
        try:
            scan_script_safety(source)
        except SafetyScanError as exc:
            return _err_result(
                ref,
                exit_code=-1,
                err=SkillExecutionError(kind="safety_scan_rejected", message=str(exc)),
            )

        # base64 注入 iOS 主题与 data(纯 ASCII,免一切引号/转义坑)
        ios_b64 = base64.b64encode(json.dumps(ios_template_layout()).encode("utf-8")).decode(
            "ascii"
        )
        data_b64 = base64.b64encode(json.dumps(payload, default=str).encode("utf-8")).decode(
            "ascii"
        )
        wrapper = _WRAPPER_SRC.replace("__IOS_B64__", ios_b64).replace("__DATA_B64__", data_b64)

        run_id = uuid.uuid4().hex[:8]
        with make_skill_workdir(run_id=run_id, root=self._workdir_root) as wd:
            (wd / "user_code.py").write_text(source, encoding="utf-8")
            interp = wd / "interp.py"
            interp.write_text(wrapper, encoding="utf-8")
            # payload 仍喂 stdin(向后兼容旧式 json.load(sys.stdin) 的用户码)
            return await self._run_subprocess(
                ref, interp, SkillScriptArgs(payload=payload), wd, timeout
            )

    async def _run_subprocess(
        self,
        ref: SkillScriptRef,
        script_full: Path,
        args: SkillScriptArgs,
        cwd: Path,
        timeout_s: int,
    ) -> SkillExecutionResult:
        start = time.monotonic()
        windows_gated = os.name == "nt"
        command = (
            [sys.executable, "-c", _WINDOWS_GATE_BOOTSTRAP, str(script_full)]
            if windows_gated
            else [sys.executable, str(script_full)]
        )
        try:
            proc = subprocess.Popen(
                command,
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

        windows_job: _WindowsJob | None = None
        if windows_gated:
            try:
                windows_job = _create_windows_job(
                    proc,
                    memory_mb=self._max_memory_mb,
                )
            except Exception as exc:
                _terminate_process_tree(proc)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.communicate(timeout=2)
                return _err_result(
                    ref,
                    exit_code=-1,
                    err=SkillExecutionError(
                        kind="sandbox_setup_failed",
                        message=f"Windows Job Object setup failed: {exc}",
                    ),
                )

        stdin_blob = json.dumps(args.payload).encode("utf-8")
        if windows_gated:
            stdin_blob = _WINDOWS_GATE_TOKEN + stdin_blob
        try:
            try:
                # C60: get_event_loop() deprecated in 3.10+; get_running_loop() is correct
                # inside an async def (loop is always running here).
                stdout_b, stderr_b = await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: proc.communicate(input=stdin_blob, timeout=timeout_s),
                )
            except subprocess.TimeoutExpired:
                if windows_job is not None:
                    windows_job.close()
                _terminate_process_tree(proc)
                try:
                    stdout_b, stderr_b = proc.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
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
                memory_limited = (
                    windows_job is not None and windows_job.memory_limit_hit(stderr_b)
                )
                error = (
                    SkillExecutionError(
                        kind="memory_limit",
                        message=f"exceeded {self._max_memory_mb}MB process memory limit",
                    )
                    if memory_limited
                    else SkillExecutionError(
                        kind="non_zero_exit",
                        message=f"exit code {proc.returncode}",
                    )
                )
                return SkillExecutionResult(
                    ok=False,
                    stdout_json=None,
                    stderr_text=stderr_text,
                    exit_code=proc.returncode,
                    elapsed_s=elapsed,
                    skill_name=ref.skill_name,
                    script_path=ref.script_path,
                    error=error,
                )

            # C34: empty stdout on exit-0 → error result to avoid model_validator crash
            if not stdout_text.strip():
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
                        message="script exited 0 but produced no stdout",
                    ),
                )

            try:
                stdout_json = json.loads(stdout_text)
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
        finally:
            if windows_job is not None:
                windows_job.close()


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
