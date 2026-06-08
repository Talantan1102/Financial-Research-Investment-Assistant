"""InProcessTool — chatloop 的轻量工具协议(spec § 3.3)。

为什么不直接用 Tool ABC:Tool.run(args) 是纯签名(只收 validated args),
但记忆类工具需要 turn 级上下文(user_id 在 state.user_id,evidence_quote 校验
要读 state.messages 里本 turn 的 user 消息)。这类"碰 harness 内部状态"的工具
(spec § 3.3 判据)需要 run 时拿到 ChatLoopState。

设计:InProcessTool 与 Tool ABC 并存。ToolHub._dispatch_one 对 isinstance
InProcessTool 的实例调 run_with_state(args, state),否则走旧 tool.run(args)。
两者都暴露 name / description / args_schema(schema_for_llm 复用),只是 run 入口不同。
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from pydantic import BaseModel

from app.chatloop.state import ChatLoopState
from app.tools.base import Tool


class InProcessTool(Tool):
    """需要 turn 级状态的 in-process 工具(记忆/控制类)。

    继承 Tool 以复用 name/description/args_schema/schema_for_llm,但 dispatch 走
    run_with_state(state 注入)。run(args) 仍是 Tool ABC 的抽象方法 —— 子类用
    一个 fail-loud 实现兜底(InProcessTool 绝不应被当普通 Tool 调,误用即报错)。
    """

    @abstractmethod
    async def run_with_state(self, args: BaseModel, state: ChatLoopState) -> dict[str, Any]:
        """执行工具,可读 state(user_id / messages / ledger ...)。"""

    async def run(self, args: BaseModel) -> dict[str, Any]:
        """Tool ABC 兜底 —— InProcessTool 必须经 run_with_state 调,直接 run 是误用。"""
        raise RuntimeError(
            f"{type(self).__name__} 是 InProcessTool,须经 ToolHub.dispatch "
            f"(run_with_state 注入 state)调用,不能走纯 run(args)"
        )


__all__ = ["InProcessTool"]
