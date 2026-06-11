"""SkillExecutorBackend — ExecutorBackend 适配层 L0 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.skills.executor_backend import SkillExecutorBackend
from app.skills.skill_executor import SkillExecutor


@pytest.mark.asyncio
async def test_backend_run_code_delegates_to_execute_source(tmp_path: Path) -> None:
    executor = SkillExecutor(skills_root=tmp_path / "s", workdir_root=tmp_path / "wd")
    backend = SkillExecutorBackend(executor)
    # 新契约(wrapper 模式):data 是命名空间变量,赋 result 即可。
    res = await backend.run_code(source="result = data['x'] * 10", data={"x": 4}, timeout_s=10)
    assert res.ok is True
    assert res.stdout_json is not None
    assert res.stdout_json["result"] == 40
