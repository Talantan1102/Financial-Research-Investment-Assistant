"""CodeInterpreterTool — name="run_python"(spec § 3)。

LLM 当场写 Python,经 ExecutorBackend 沙箱执行,返回 {result, figures, stderr,
elapsed_s}。figures(plotly fig.to_dict() 列表)由 ToolLoop 抽出发 chart 事件并从
输出剥离 —— 工具本身只负责"执行 + 透传",不碰 SSE/缓存(职责单一)。

执行失败(safety_scan_rejected / non_zero_exit / timeout / stdout_invalid_json)
→ 抛 ToolError(带 stderr),hub 的 _guidance_error 见 '[' 前缀原样透出,LLM 据
stderr 改代码重试(chatloop while 循环天然承载自纠)。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.chatloop.inprocess import InProcessTool
from app.chatloop.state import ChatLoopState
from app.skills.executor_backend import ExecutorBackend
from app.tools.base import ToolError

_STDERR_FEEDBACK_LEN = 500  # 回喂模型自纠的 stderr 截断


class CodeInterpreterArgs(BaseModel):
    code: str
    data: dict[str, Any] | None = None


class CodeInterpreterTool(InProcessTool):
    name = "run_python"
    description = "执行 Python 做数值计算/画交互分析图(plotly)。需二次计算或可视化时用。"
    args_schema = CodeInterpreterArgs

    def __init__(self, *, backend: ExecutorBackend, timeout_s: int = 30) -> None:
        self._backend = backend
        self._timeout_s = timeout_s

    async def run_with_state(self, args: BaseModel, state: ChatLoopState) -> dict[str, Any]:
        args = CodeInterpreterArgs.model_validate(args.model_dump())
        result = await self._backend.run_code(
            source=args.code, data=args.data or {}, timeout_s=self._timeout_s
        )
        if not result.ok:
            kind = result.error.kind if result.error else "unknown"
            stderr = result.stderr_text[:_STDERR_FEEDBACK_LEN]
            raise ToolError(f"[执行失败:{kind}] 代码执行未成功。\nstderr: {stderr}")

        out = result.stdout_json or {}
        return {
            "result": out.get("result"),
            "figures": out.get("figures") or [],
            "stderr": result.stderr_text[:_STDERR_FEEDBACK_LEN],
            "elapsed_s": round(result.elapsed_s, 2),
        }


__all__ = ["CodeInterpreterArgs", "CodeInterpreterTool"]
