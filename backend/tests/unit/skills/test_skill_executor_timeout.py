"""L0 — SIGKILL on timeout overrun + process tree cleanup."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest
from app.skills.script_schemas import SkillScriptArgs, SkillScriptRef
from app.skills.skill_executor import SkillExecutor


@pytest.fixture
def fake_skills_root(tmp_path):
    skill = tmp_path / "claude_skills" / "demo"
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text("# demo")
    return tmp_path / "claude_skills"


@pytest.mark.asyncio
async def test_executor_sigkills_on_timeout(fake_skills_root, tmp_path):
    script = fake_skills_root / "demo" / "scripts" / "sleep60.py"
    script.write_text(
        "import json, time\ntime.sleep(60)\nprint(json.dumps({'unreachable': True}))\n"
    )
    ex = SkillExecutor(
        skills_root=fake_skills_root,
        workdir_root=tmp_path / "wd",
    )
    start = time.monotonic()
    result = await ex.execute(
        ref=SkillScriptRef(skill_name="demo", script_path="scripts/sleep60.py"),
        args=SkillScriptArgs(payload={}),
        timeout_s=5,
    )
    elapsed = time.monotonic() - start
    assert result.ok is False
    assert result.error.kind == "timeout"
    assert result.exit_code == -9
    assert elapsed < 12, f"timeout enforcement too slow: {elapsed}s"


@pytest.mark.asyncio
async def test_executor_caps_timeout_to_max(fake_skills_root, tmp_path):
    script = fake_skills_root / "demo" / "scripts" / "echo.py"
    script.write_text("import json, sys\ndata = json.load(sys.stdin)\nprint(json.dumps(data))\n")
    ex = SkillExecutor(
        skills_root=fake_skills_root,
        workdir_root=tmp_path / "wd",
        max_timeout_s=10,
    )
    result = await ex.execute(
        ref=SkillScriptRef(skill_name="demo", script_path="scripts/echo.py"),
        args=SkillScriptArgs(payload={"x": 1}),
        timeout_s=999,
    )
    assert result.ok is True


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="fork() is POSIX-only")
async def test_executor_kills_subprocess_tree(fake_skills_root, tmp_path):
    script = fake_skills_root / "demo" / "scripts" / "fork_and_sleep.py"
    script.write_text(
        "import os, time, sys, json\n"
        "pid = os.fork()\n"
        "if pid == 0:\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "else:\n"
        "    print(json.dumps({'parent_pid': os.getpid(), 'child_pid': pid}), flush=True)\n"
        "    time.sleep(60)\n"
    )
    ex = SkillExecutor(
        skills_root=fake_skills_root,
        workdir_root=tmp_path / "wd",
    )
    result = await ex.execute(
        ref=SkillScriptRef(skill_name="demo", script_path="scripts/fork_and_sleep.py"),
        args=SkillScriptArgs(payload={}),
        timeout_s=3,
    )
    assert result.ok is False
    assert result.error.kind == "timeout"


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object only")
@pytest.mark.asyncio
async def test_windows_timeout_kills_child_process_tree(tmp_path: Path) -> None:
    marker = tmp_path / "orphan-marker.txt"
    child_source = (
        "import time\n"
        "from pathlib import Path\n"
        "time.sleep(4)\n"
        f"Path({str(marker)!r}).write_text('orphan survived')\n"
    )
    script = tmp_path / "spawn-child.py"
    script.write_text(
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {child_source!r}])\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    executor = SkillExecutor(skills_root=tmp_path, workdir_root=tmp_path / "wd")

    result = await executor._run_subprocess(
        SkillScriptRef(skill_name="demo", script_path="scripts/spawn-child.py"),
        script,
        SkillScriptArgs(payload={}),
        tmp_path,
        1,
    )
    await asyncio.sleep(5)

    assert result.ok is False
    assert result.error.kind == "timeout"
    assert not marker.exists()
