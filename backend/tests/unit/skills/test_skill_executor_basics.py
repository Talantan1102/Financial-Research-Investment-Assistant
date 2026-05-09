"""L0 — SkillExecutor basics: subprocess launch + cwd + env scrub."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.skills.script_schemas import SkillScriptArgs, SkillScriptRef
from app.skills.skill_executor import SkillExecutor


@pytest.fixture
def fake_skills_root(tmp_path: Path) -> Path:
    skill = tmp_path / "claude_skills" / "demo_skill"
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text("# demo")
    return tmp_path / "claude_skills"


def _write_script(skills_root: Path, name: str, body: str) -> SkillScriptRef:
    p = skills_root / "demo_skill" / "scripts" / name
    p.write_text(body)
    return SkillScriptRef(skill_name="demo_skill", script_path=f"scripts/{name}")


@pytest.mark.asyncio
async def test_executor_runs_simple_script_returns_json(fake_skills_root, tmp_path):
    ref = _write_script(
        fake_skills_root,
        "echo.py",
        "import json, sys\ndata = json.load(sys.stdin)\nprint(json.dumps({'echoed': data}))\n",
    )
    ex = SkillExecutor(
        skills_root=fake_skills_root,
        workdir_root=tmp_path / "wd",
    )
    result = await ex.execute(
        ref=ref,
        args=SkillScriptArgs(payload={"hello": "world"}),
    )
    assert result.ok is True
    assert result.stdout_json == {"echoed": {"hello": "world"}}
    assert result.exit_code == 0


@pytest.mark.asyncio
async def test_executor_cwd_isolated_to_workdir(fake_skills_root, tmp_path):
    ref = _write_script(
        fake_skills_root,
        "writefile.py",
        "import json, sys, os\n"
        "open('marker.txt', 'w').write('here')\n"
        "print(json.dumps({'cwd': os.getcwd()}))\n",
    )
    ex = SkillExecutor(skills_root=fake_skills_root, workdir_root=tmp_path / "wd")
    result = await ex.execute(ref=ref, args=SkillScriptArgs(payload={}))
    assert result.ok is True
    assert "wd" in result.stdout_json["cwd"]


@pytest.mark.asyncio
async def test_executor_env_scrubbed_to_minimal_whitelist(fake_skills_root, tmp_path, monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-secret-leak-me-not")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    ref = _write_script(
        fake_skills_root,
        "envcheck.py",
        "import json, os, sys\n"
        "print(json.dumps({'api_key': os.environ.get('DASHSCOPE_API_KEY'), "
        "                  'path_present': 'PATH' in os.environ}))\n",
    )
    ex = SkillExecutor(skills_root=fake_skills_root, workdir_root=tmp_path / "wd")
    result = await ex.execute(ref=ref, args=SkillScriptArgs(payload={}))
    assert result.ok is True
    assert result.stdout_json["api_key"] is None
    assert result.stdout_json["path_present"] is True


@pytest.mark.asyncio
async def test_executor_rejects_unknown_skill(tmp_path):
    ex = SkillExecutor(skills_root=tmp_path / "claude_skills", workdir_root=tmp_path / "wd")
    ref = SkillScriptRef(skill_name="ghost_skill", script_path="scripts/x.py")
    result = await ex.execute(ref=ref, args=SkillScriptArgs(payload={}))
    assert result.ok is False
    assert result.error.kind == "subprocess_launch_failed"
