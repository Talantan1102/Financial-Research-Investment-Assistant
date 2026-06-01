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
    # C33 banned open(); this test only needs to observe the script's cwd, so
    # report os.getcwd() directly (the marker-file write was incidental).
    ref = _write_script(
        fake_skills_root,
        "writefile.py",
        "import json, sys, os\nprint(json.dumps({'cwd': os.getcwd()}))\n",
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


@pytest.mark.asyncio
async def test_executor_handles_stdout_invalid_json(fake_skills_root, tmp_path):
    ref = _write_script(fake_skills_root, "freetext.py", "print('hello world, not json')\n")
    ex = SkillExecutor(skills_root=fake_skills_root, workdir_root=tmp_path / "wd")
    result = await ex.execute(ref=ref, args=SkillScriptArgs(payload={}))
    assert result.ok is False
    assert result.error.kind == "stdout_invalid_json"


@pytest.mark.asyncio
async def test_executor_truncates_stderr_to_2kb(fake_skills_root, tmp_path):
    ref = _write_script(
        fake_skills_root,
        "spew.py",
        "import sys, json\nsys.stderr.write('X' * 5000)\nprint(json.dumps({'ok': True}))\n",
    )
    ex = SkillExecutor(
        skills_root=fake_skills_root,
        workdir_root=tmp_path / "wd",
        stderr_max_bytes=2048,
    )
    result = await ex.execute(ref=ref, args=SkillScriptArgs(payload={}))
    assert result.ok is True
    assert len(result.stderr_text) <= 2048 + 50
    assert "[truncated]" in result.stderr_text


@pytest.mark.asyncio
async def test_executor_passes_complex_args_via_stdin(fake_skills_root, tmp_path):
    ref = _write_script(
        fake_skills_root,
        "roundtrip.py",
        "import json, sys\n"
        "data = json.load(sys.stdin)\n"
        "data['marker'] = 'roundtripped'\n"
        "print(json.dumps(data))\n",
    )
    payload = {
        "financials": {"revenue": [100, 110, 120], "ebit": [20, 22, 25]},
        "wacc": 0.085,
        "horizon_years": 5,
    }
    ex = SkillExecutor(skills_root=fake_skills_root, workdir_root=tmp_path / "wd")
    result = await ex.execute(ref=ref, args=SkillScriptArgs(payload=payload))
    assert result.ok is True
    assert result.stdout_json["marker"] == "roundtripped"
    assert result.stdout_json["financials"]["revenue"] == [100, 110, 120]


@pytest.mark.asyncio
async def test_executor_non_zero_exit_propagates(fake_skills_root, tmp_path):
    ref = _write_script(
        fake_skills_root,
        "fail.py",
        "import sys\nsys.stderr.write('something went wrong')\nsys.exit(2)\n",
    )
    ex = SkillExecutor(skills_root=fake_skills_root, workdir_root=tmp_path / "wd")
    result = await ex.execute(ref=ref, args=SkillScriptArgs(payload={}))
    assert result.ok is False
    assert result.error.kind == "non_zero_exit"
    assert result.exit_code == 2
    assert "something went wrong" in result.stderr_text


@pytest.mark.asyncio
async def test_executor_rejects_script_with_banned_api(fake_skills_root, tmp_path):
    """S9 — script containing os.system must be rejected before launch."""
    ref = _write_script(
        fake_skills_root,
        "evil.py",
        "import os, json\nos.system('echo hacked')\nprint(json.dumps({'pwned': True}))\n",
    )
    ex = SkillExecutor(skills_root=fake_skills_root, workdir_root=tmp_path / "wd")
    result = await ex.execute(ref=ref, args=SkillScriptArgs(payload={}))
    assert result.ok is False
    assert result.error.kind == "safety_scan_rejected"
    assert "os.system" in result.error.message


# C34 — exit-0 with empty stdout must yield ok=False (stdout_invalid_json)
# rather than crash with pydantic ValidationError.


@pytest.mark.asyncio
async def test_executor_exit0_empty_stdout_returns_error(fake_skills_root, tmp_path):
    """Script exits 0 but writes nothing to stdout → ok=False, not ValidationError."""
    ref = _write_script(
        fake_skills_root,
        "silent_exit.py",
        "import sys\n# intentionally writes no stdout\nsys.exit(0)\n",
    )
    ex = SkillExecutor(skills_root=fake_skills_root, workdir_root=tmp_path / "wd")
    result = await ex.execute(ref=ref, args=SkillScriptArgs(payload={}))
    assert result.ok is False
    assert result.error.kind == "stdout_invalid_json"
    assert "no stdout" in result.error.message


@pytest.mark.asyncio
async def test_executor_exit0_nonjson_stdout_returns_error(fake_skills_root, tmp_path):
    """Script exits 0 with non-JSON output → ok=False, kind stdout_invalid_json."""
    ref = _write_script(
        fake_skills_root,
        "plain_text.py",
        "print('this is not JSON at all')\n",
    )
    ex = SkillExecutor(skills_root=fake_skills_root, workdir_root=tmp_path / "wd")
    result = await ex.execute(ref=ref, args=SkillScriptArgs(payload={}))
    assert result.ok is False
    assert result.error.kind == "stdout_invalid_json"


# C60 — get_running_loop() must not emit DeprecationWarning on Python 3.10+.


@pytest.mark.asyncio
@pytest.mark.filterwarnings("error::DeprecationWarning")
async def test_executor_no_event_loop_deprecation_warning(fake_skills_root, tmp_path):
    """asyncio.get_running_loop() must be used (no DeprecationWarning in 3.10+)."""
    ref = _write_script(
        fake_skills_root,
        "echo2.py",
        "import json, sys\ndata = json.load(sys.stdin)\nprint(json.dumps({'echoed': data}))\n",
    )
    ex = SkillExecutor(skills_root=fake_skills_root, workdir_root=tmp_path / "wd")
    result = await ex.execute(ref=ref, args=SkillScriptArgs(payload={"x": 1}))
    assert result.ok is True
