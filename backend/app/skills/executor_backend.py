"""ExecutorBackend — 代码解释器的执行后端抽象(spec § 4)。

v1.0 唯一实现 SkillExecutorBackend(复用 subprocess+rlimit+AST 沙箱);
DockerExecutorBackend 是 v1.x 留口子——接口已定,真要更强隔离再实装,
工具层(CodeInterpreterTool)只依赖本 Protocol,不动工具就能换后端。
"""

from __future__ import annotations

from typing import Any, Protocol

from app.skills.script_schemas import SkillExecutionResult
from app.skills.skill_executor import SkillExecutor


class ExecutorBackend(Protocol):
    """代码执行后端契约。"""

    async def run_code(
        self, *, source: str, data: dict[str, Any], timeout_s: int
    ) -> SkillExecutionResult: ...


class SkillExecutorBackend:
    """v1.0 后端 —— 委派给 SkillExecutor.execute_source。"""

    def __init__(self, executor: SkillExecutor) -> None:
        self._executor = executor

    async def run_code(
        self, *, source: str, data: dict[str, Any], timeout_s: int
    ) -> SkillExecutionResult:
        return await self._executor.execute_source(
            source=source, payload=data, timeout_s=timeout_s
        )


__all__ = ["ExecutorBackend", "SkillExecutorBackend"]
