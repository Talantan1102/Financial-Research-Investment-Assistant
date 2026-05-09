"""Responder — final LangGraph agent: produces full-text natural-language reply.

Consumes GraphState (user_message + tool_results) and asks the LLM to
synthesize a concise Chinese reply. v0 is synchronous — LangGraph streaming
happens at the node layer (Task 11), not inside Responder.

v0.9 adds async run(ChatState) per spec § 4.1:
  - LLM-driven projection: pass full tool result JSON, let LLM pick relevant fields (B2)
  - Soft-answer on tool error (C2)
"""

from __future__ import annotations

import json
from typing import Any

from app.agents.base import Agent
from app.agents.schemas import ChatState, GraphState, StepResult, ToolResult
from app.services.llm_response import Tier
from app.services.llm_service import LLMService

# System role prefix — MUST differ from ChatPlanner's "你是金融研究助手 planner。"
# so mock fixture patterns don't shadow each other.
_SYSTEM_ROLE = "你是金融研究助手 responder。"

# v0.9 prompt template for async run() — LLM-driven tool result projection (B2/C2)
_RESPONDER_V09_PROMPT = """\
你是金融研究助手 chat 模式的 responder,根据下面的信息生成回答用户的话。

用户问题:
{user_message}

历史摘要(如有):
{history_summary}

工具调用结果(JSON 格式,某些可能失败 success=false):
{tool_results}

要求:
- 用中文,简洁、准确、不要堆砌
- 只引用 tool 结果中跟用户问题相关的字段
- 如果有 tool 失败 (ERROR),用一两句话说明并建议用户稍后再试,不要编造数据
- 数字保留 2 位小数

回答:
"""


def _format_tool_result(tr: ToolResult) -> str:
    """Render a single ToolResult as a compact text block for the prompt."""
    if tr.success:
        return f"- 工具: {tr.tool_name}\n  状态: 成功\n  结果: {tr.output}"
    return f"- 工具: {tr.tool_name}\n  状态: 失败\n  错误: {tr.error}"


def build_responder_prompt(state: GraphState) -> str:
    """Build the responder prompt: system role + tool results + user message + instruction.

    Args:
        state: Current graph state containing user_message and tool_results.

    Returns:
        A multi-section prompt string ready for LLMService.chat().
    """
    if state.tool_results:
        results_section = "\n".join(_format_tool_result(tr) for tr in state.tool_results)
        tool_block = f"## 工具调用结果\n\n{results_section}\n\n"
    else:
        tool_block = "## 工具调用结果\n\n（无工具调用）\n\n"

    prompt = (
        f"{_SYSTEM_ROLE}\n\n"
        "## 用户问题\n\n"
        f"{state.user_message}\n\n"
        f"{tool_block}"
        "## 回复要求\n\n"
        "请根据上方工具结果，用简洁中文直接回答用户问题。"
        "如果工具调用失败，说明无法获取相关数据并建议用户稍后重试。"
        "不要重复工具原始输出，直接给出结论性回答。"
    )
    return prompt


class Responder(Agent):
    """Synthesize tool results into a single full-text Chinese reply.

    Uses prompt-engineered free-text — the LLM is asked to produce a
    natural-language answer. No JSON schema is used here.
    v0 streaming happens at the LangGraph node layer (Task 11).
    """

    name = "Responder"
    model_tier: Tier = "fast"

    def __init__(self, llm: LLMService) -> None:
        super().__init__(llm)

    def step(self, state: GraphState) -> StepResult:
        """Build a responder prompt, call LLM, return final_response."""
        prompt = build_responder_prompt(state=state)
        r = self._llm.chat(
            prompt=prompt,
            tier=self.model_tier,
            request_id=state.request_id,
        )
        return StepResult(
            state_update={"final_response": r.content},
            span_metadata={
                "agent": "Responder",
                "model": r.model,
                "cost_cny": r.cost_cny,
            },
        )

    async def run(self, state: ChatState) -> dict[str, Any]:
        """v0.9 async entry point — LLM-driven projection of tool results (B2/C2).

        Passes full tool result JSON to LLM; soft-answers on tool failures.
        """
        tool_block = self._format_chat_tool_results(state)
        prompt = _RESPONDER_V09_PROMPT.format(
            user_message=state.user_message,
            history_summary=state.history_summary or "(无)",
            tool_results=tool_block,
        )
        resp = self._llm.chat(prompt=prompt, tier="default", schema=None)
        return {"final_response": resp.content.strip()}

    def _format_chat_tool_results(self, state: ChatState) -> str:
        """Serialize ChatState tool_results as JSON lines for the LLM prompt."""
        if not state.tool_results:
            return "(无工具调用)"
        lines = []
        for r in state.tool_results:
            args_str = json.dumps(r.args, ensure_ascii=False)
            if r.success:
                output_str = json.dumps(r.output or {}, ensure_ascii=False)
                lines.append(f"- {r.tool_name}({args_str}) → {output_str}")
            else:
                lines.append(f"- {r.tool_name}({args_str}) → ERROR: {r.error or 'unknown'}")
        return "\n".join(lines)
