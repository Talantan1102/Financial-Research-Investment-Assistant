"""L0 — resource limits via preexec_fn."""

from __future__ import annotations

import os
import platform
from pathlib import Path

import app.skills.skill_executor as skill_executor
import pytest
from app.skills.script_schemas import SkillScriptArgs, SkillScriptRef
from app.skills.skill_executor import SkillExecutor, _apply_rlimits


@pytest.fixture
def fake_skills_root(tmp_path):
    skill = tmp_path / "claude_skills" / "demo"
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text("# demo")
    return tmp_path / "claude_skills"


def test_apply_rlimits_returns_callable():
    fn = _apply_rlimits(memory_mb=256, cpu_seconds=30)
    if os.name == "posix":
        assert callable(fn)
    else:
        assert fn is None


@pytest.mark.skipif(
    platform.system() == "Darwin",
    reason="RLIMIT_AS is unreliable on macOS",
)
@pytest.mark.asyncio
async def test_executor_kills_oom_script(fake_skills_root, tmp_path):
    script = fake_skills_root / "demo" / "scripts" / "oom.py"
    script.write_text(
        "import json, sys\n"
        "x = bytearray(512 * 1024 * 1024)\n"
        "print(json.dumps({'allocated': len(x)}))\n"
    )
    ex = SkillExecutor(
        skills_root=fake_skills_root,
        workdir_root=tmp_path / "wd",
        max_memory_mb=256,
    )
    result = await ex.execute(
        ref=SkillScriptRef(skill_name="demo", script_path="scripts/oom.py"),
        args=SkillScriptArgs(payload={}),
    )
    assert result.ok is False
    if os.name == "nt":
        assert result.error.kind == "memory_limit"
    else:
        assert result.error.kind in {"non_zero_exit", "memory_limit"}


@pytest.mark.asyncio
async def test_executor_under_memory_limit_succeeds(fake_skills_root, tmp_path):
    script = fake_skills_root / "demo" / "scripts" / "tiny.py"
    script.write_text(
        "import json\nx = bytearray(1024 * 1024)\nprint(json.dumps({'ok': True, 'len': len(x)}))\n"
    )
    ex = SkillExecutor(
        skills_root=fake_skills_root,
        workdir_root=tmp_path / "wd",
        max_memory_mb=256,
    )
    result = await ex.execute(
        ref=SkillScriptRef(skill_name="demo", script_path="scripts/tiny.py"),
        args=SkillScriptArgs(payload={}),
    )
    assert result.ok is True
    assert result.stdout_json["len"] == 1024 * 1024


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object only")
@pytest.mark.asyncio
async def test_windows_job_setup_failure_never_executes_untrusted_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "must-not-exist.txt"
    script = tmp_path / "marker.py"
    script.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\nprint('{{}}')\n",
        encoding="utf-8",
    )

    def _fail_job_setup(*_args, **_kwargs):
        raise OSError("job setup failed")

    monkeypatch.setattr(skill_executor, "_create_windows_job", _fail_job_setup)
    executor = SkillExecutor(skills_root=tmp_path, workdir_root=tmp_path / "wd")
    result = await executor._run_subprocess(
        SkillScriptRef(skill_name="demo", script_path="scripts/marker.py"),
        script,
        SkillScriptArgs(payload={}),
        tmp_path,
        5,
    )

    assert result.ok is False
    assert result.error.kind == "sandbox_setup_failed"
    assert not marker.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object only")
@pytest.mark.asyncio
async def test_windows_job_handle_is_closed_after_success(
    fake_skills_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_jobs = []
    close_calls = 0
    original_create = skill_executor._create_windows_job

    def _tracked_create(*args, **kwargs):
        nonlocal close_calls
        job = original_create(*args, **kwargs)
        original_close = job.close

        def _tracked_close() -> None:
            nonlocal close_calls
            close_calls += 1
            original_close()

        job.close = _tracked_close
        created_jobs.append(job)
        return job

    monkeypatch.setattr(skill_executor, "_create_windows_job", _tracked_create)
    script = fake_skills_root / "demo" / "scripts" / "tracked.py"
    script.write_text("import json\nprint(json.dumps({'ok': True}))\n")
    executor = SkillExecutor(
        skills_root=fake_skills_root,
        workdir_root=tmp_path / "wd",
    )

    result = await executor.execute(
        ref=SkillScriptRef(skill_name="demo", script_path="scripts/tracked.py"),
        args=SkillScriptArgs(payload={}),
    )

    assert result.ok is True
    assert len(created_jobs) == 1
    assert created_jobs[0]._closed is True
    assert close_calls == 1
