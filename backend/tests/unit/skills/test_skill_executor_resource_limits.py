"""L0 — resource limits via preexec_fn."""

from __future__ import annotations

import os
import platform

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
    platform.system() in {"Darwin", "Windows"},
    reason="RLIMIT_AS unavailable or unreliable on this platform",
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
