"""execute_source — SkillExecutor 内联源码执行入口的 L0 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.skills.skill_executor import SkillExecutor


@pytest.fixture
def executor(tmp_path: Path) -> SkillExecutor:
    # skills_root 对 execute_source 无意义(不读磁盘脚本),给个空目录即可。
    return SkillExecutor(skills_root=tmp_path / "skills", workdir_root=tmp_path / "wd")


@pytest.mark.asyncio
async def test_execute_source_ok_returns_stdout_json(executor: SkillExecutor) -> None:
    # 新契约(wrapper 模式):data 是命名空间变量,赋 result 即可,不用 print。
    res = await executor.execute_source(
        source="result = data['a'] + data['b']", payload={"a": 2, "b": 3}
    )
    assert res.ok is True
    assert res.stdout_json["result"] == 5
    assert res.stdout_json["figures"] == []


@pytest.mark.asyncio
async def test_execute_source_rejects_banned_open(executor: SkillExecutor) -> None:
    src = "open('/etc/passwd')\n"
    res = await executor.execute_source(source=src, payload={})
    assert res.ok is False
    assert res.error is not None
    assert res.error.kind == "safety_scan_rejected"


@pytest.mark.asyncio
async def test_execute_source_non_zero_exit_carries_stderr(executor: SkillExecutor) -> None:
    src = "raise ValueError('boom')\n"
    res = await executor.execute_source(source=src, payload={})
    assert res.ok is False
    assert res.error is not None
    assert res.error.kind == "non_zero_exit"
    assert "boom" in res.stderr_text
