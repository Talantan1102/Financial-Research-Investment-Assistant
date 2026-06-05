"""ChatLoopAgent — 评测 SUT,用 ToolLoop 跑一问一答(spec § 5.2 评测换靶)。

老 ChatAgent SUT 包 LangGraph 单程图、从 plan.tool_calls 抽业务工具调用;裸 while
重设计后没有 plan 这一结构化中间产物,工具调用散落在 final.messages 的 assistant
tool_calls 里(原始 arguments JSON 在那)。本 SUT 替代老 ChatAgent:

- 构造注入与 worker_wiring 同款组件(llm / tool_hub / context_deps / gate_cfg),
  测试给 Scripted/Fake,真跑给真件;
- run() 跑完一个 turn,从 **final.messages 的 assistant tool_calls 抽** SUTOutput
  .tool_calls(ledger 只有 args_hash,没有原始 args,故不从台账抽 args)。

口径决策(spec § 5.2 + 任务说明):
- ``search_tools`` 排除出 tool_calls —— Judge 的 golden expected tool_calls 评的是
  业务工具(数据/记忆/技能/控制),检索工具文档是渐进披露的机制行为,不是业务意图。
  保留它会把"模型先查了一次工具文档"算成一次业务工具调用,污染 tool_correctness。
- 坏 JSON args 容错:json.loads 失败兜 {}(模型偶发产非法 arguments,不应让整个
  评测炸;Judge 看到空 args 自会扣 tool_correctness)。
- ToolCall.rationale 是老 plan 时代的必填字段,裸 while 下 assistant tool_calls 不带
  rationale,此处填空串(Judge 评的是 tool_name+args,rationale 非评分维度)。
"""
from __future__ import annotations

import json
from typing import Any

from app.agents.schemas import ToolCall
from app.chatloop.context import ContextDeps
from app.chatloop.gates import GateConfig
from app.chatloop.loop import ToolHubProtocol, ToolLoop
from app.chatloop.state import ChatLoopState
from app.services.eval_models import SUTOutput

# search_tools 排除口径(spec § 3.2 渐进披露的机制工具,非业务工具)
_SEARCH_TOOLS_NAME = "search_tools"


class ChatLoopAgent:
    """评测 SUT — 用 ToolLoop 跑一问一答(满足 ``SUT`` Protocol)。

    构造注入与 worker_wiring 同款组件(测试给 Scripted/Fake;真跑给真件)。
    """

    def __init__(
        self,
        *,
        llm: Any,
        tool_hub: ToolHubProtocol,
        context_deps: ContextDeps,
        gate_cfg: GateConfig | None = None,
    ) -> None:
        self._llm = llm
        self._tool_hub = tool_hub
        self._context_deps = context_deps
        self._gate_cfg = gate_cfg

    async def run(self, user_input: str, request_id: str) -> SUTOutput:
        state = ChatLoopState(
            user_id="eval",
            session_id=f"eval-{request_id}",
            request_id=request_id,
            messages=[{"role": "user", "content": user_input}],
        )
        loop = ToolLoop(
            llm=self._llm,
            tool_hub=self._tool_hub,
            context_deps=self._context_deps,
            gate_cfg=self._gate_cfg,
        )
        final = await loop.run(state)

        return SUTOutput(
            request_id=request_id,
            response_text=final.final_response or self._last_assistant_content(final),
            tool_calls=self._extract_tool_calls(final),
            escalate_offered=final.escalate_offered,
        )

    # ------------------------------------------------------------------
    # 抽取:tool_calls 从 messages 台账(原始 args 在 assistant tool_calls 里)
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_tool_calls(state: ChatLoopState) -> list[ToolCall]:
        """从 final.messages 的 assistant tool_calls 抽业务工具调用(排除 search_tools)。

        ledger.entries 只有 tool_name + args_hash(没有原始 args),故原始 arguments
        JSON 只能从 assistant 消息的 tool_calls[].function.arguments 取(spec § 5.2)。
        """
        out: list[ToolCall] = []
        for msg in state.messages:
            if msg.get("role") != "assistant":
                continue
            for tc in msg.get("tool_calls", []) or []:
                fn = tc.get("function", {})
                name = fn.get("name")
                if name is None or name == _SEARCH_TOOLS_NAME:
                    continue
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                    if not isinstance(args, dict):
                        args = {}
                except (json.JSONDecodeError, ValueError):
                    args = {}
                out.append(ToolCall(tool_name=name, args=args, rationale=""))
        return out

    @staticmethod
    def _last_assistant_content(state: ChatLoopState) -> str:
        """final_response 为空时兜底:取最后一条有 content 的 assistant 消息。"""
        for msg in reversed(state.messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                content = msg["content"]
                if isinstance(content, str):
                    return content
        return ""


__all__ = ["ChatLoopAgent"]
