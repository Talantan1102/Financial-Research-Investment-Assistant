"""CodeInterpreterTool — run_python 工具 L0 测试(用 Fake backend,不起真子进程)。"""

from __future__ import annotations

from typing import Any

import pytest
from app.chatloop.code_interpreter_tool import CodeInterpreterArgs, CodeInterpreterTool
from app.skills.script_schemas import SkillExecutionError, SkillExecutionResult
from app.tools.base import ToolError


class _FakeBackend:
    def __init__(self, result: SkillExecutionResult) -> None:
        self._result = result
        self.calls: list[dict[str, Any]] = []

    async def run_code(self, *, source: str, data: dict[str, Any], timeout_s: int):
        self.calls.append({"source": source, "data": data, "timeout_s": timeout_s})
        return self._result


def _ok(stdout: dict[str, Any]) -> SkillExecutionResult:
    return SkillExecutionResult(
        ok=True,
        stdout_json=stdout,
        stderr_text="",
        exit_code=0,
        elapsed_s=0.1,
        skill_name="_interpreter",
        script_path="scripts/interp.py",
    )


def _err(kind: str, stderr: str) -> SkillExecutionResult:
    return SkillExecutionResult(
        ok=False,
        stdout_json=None,
        stderr_text=stderr,
        exit_code=1,
        elapsed_s=0.1,
        skill_name="_interpreter",
        script_path="scripts/interp.py",
        error=SkillExecutionError(kind=kind, message="x"),  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_ok_returns_result_and_figures() -> None:
    backend = _FakeBackend(_ok({"result": {"corr": 0.83}, "figures": [{"data": [], "layout": {}}]}))
    tool = CodeInterpreterTool(backend=backend)
    out = await tool.run_with_state(
        CodeInterpreterArgs(code="print('x')", data={"k": 1}),
        state=None,  # type: ignore[arg-type]
    )
    assert out["result"] == {"corr": 0.83}
    assert out["figures"] == [{"data": [], "layout": {}}]
    assert backend.calls[0]["data"] == {"k": 1}


@pytest.mark.asyncio
async def test_missing_figures_defaults_empty_list() -> None:
    backend = _FakeBackend(_ok({"result": 42}))
    tool = CodeInterpreterTool(backend=backend)
    out = await tool.run_with_state(CodeInterpreterArgs(code="x=1"), state=None)  # type: ignore[arg-type]
    assert out["figures"] == []


@pytest.mark.asyncio
async def test_exec_failure_raises_toolerror_with_stderr() -> None:
    backend = _FakeBackend(_err("non_zero_exit", "Traceback ... ValueError: boom"))
    tool = CodeInterpreterTool(backend=backend)
    with pytest.raises(ToolError) as ei:
        await tool.run_with_state(
            CodeInterpreterArgs(code="raise ValueError"),
            state=None,  # type: ignore[arg-type]
        )
    msg = str(ei.value)
    assert msg.startswith("[")  # 指导性前缀 → hub 原样透出给模型自纠
    assert "boom" in msg
