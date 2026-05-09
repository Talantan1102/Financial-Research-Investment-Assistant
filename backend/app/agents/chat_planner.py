"""ChatPlanner — first LangGraph agent: decides which tools (if any) to call.

v0.9 per spec § 4.1:
  - constrained LLM (strict JSON schema) per A3 (arg fidelity)
  - emits parallelizable: bool (A2)
  - filters hallucinated tool names against registry whitelist (A4)
  - emits escalate_offered when planner detects deep intent (Q3 hook for Plan 3)

Legacy path (ToolRegistry-based) is preserved for backwards-compat with v0
research-mode graph. v0.9 chat mode uses the new ChatPlanner(llm, available_tools)
constructor path with async run(ChatState) -> dict.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.agents.base import Agent
from app.agents.schemas import ChatState, GraphState, Plan, StepResult, ToolCall
from app.services.llm_response import Tier
from app.services.llm_service import LLMService
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# Regex to strip markdown code fences (```json ... ``` or ``` ... ```)
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)

# ---------------------------------------------------------------------------
# Legacy v0 prompt helpers (preserved for research-mode graph)
# ---------------------------------------------------------------------------

_SYSTEM_ROLE = "你是金融研究助手 planner。"

_PLAN_SCHEMA_DESCRIPTION = """\
请输出 **纯 JSON**（不含 Markdown 代码块以外任何内容），格式严格符合以下 schema：
{
  "tool_calls": [           // 若需调用工具，列出每次调用；若不需要则为空数组
    {
      "tool_name": "<工具名>",
      "args": {<工具参数 key-value>},
      "rationale": "<本次调用的简短理由>"
    }
  ],
  "direct_response": false, // true 表示无需工具可直接回答（tool_calls 必须为空）
  "reasoning": "<规划过程的一句话摘要>"
}
注意：direct_response=true 时 tool_calls 必须为空；
      direct_response=false 时 tool_calls 至少包含一个元素。"""


def _tools_to_markdown(tool_schemas: list[dict[str, Any]]) -> str:
    """Convert OpenAI-format tool schemas to a human-readable markdown list."""
    lines: list[str] = []
    for schema in tool_schemas:
        func = schema.get("function", {})
        name: str = func.get("name", "")
        description: str = func.get("description", "")
        params: dict[str, Any] = func.get("parameters", {})
        props: dict[str, Any] = params.get("properties", {})

        arg_parts: list[str] = []
        for arg_name, arg_schema in props.items():
            arg_type: str = arg_schema.get("type", "any")
            arg_desc: str = arg_schema.get("description", "")
            arg_parts.append(f"`{arg_name}` ({arg_type}){': ' + arg_desc if arg_desc else ''}")

        args_str = ", ".join(arg_parts) if arg_parts else "无参数"
        lines.append(f"- **{name}**: {description}\n  参数: {args_str}")

    return "\n".join(lines) if lines else "（暂无可用工具）"


def build_planner_prompt(state: GraphState, registry: ToolRegistry) -> str:
    """Build the planner prompt: system role + tool list + user message + JSON instruction.

    Args:
        state:    Current graph state containing user_message and request metadata.
        registry: ToolRegistry providing the available tools via list_for_llm().

    Returns:
        A multi-section prompt string ready for LLMService.chat().
    """
    tool_schemas = registry.list_for_llm()
    tools_md = _tools_to_markdown(tool_schemas)

    prompt = (
        f"{_SYSTEM_ROLE}\n\n"
        "## 可用工具\n\n"
        f"{tools_md}\n\n"
        "## 用户消息\n\n"
        f"{state.user_message}\n\n"
        "## 输出要求\n\n"
        f"{_PLAN_SCHEMA_DESCRIPTION}"
    )
    return prompt


def _parse_plan(content: str) -> Plan:
    """Strip markdown code fences (if any) then Pydantic-validate into Plan.

    Args:
        content: Raw LLM response string, possibly wrapped in ```json ... ```.

    Returns:
        Validated Plan instance.

    Raises:
        ValueError: If the content cannot be parsed as valid JSON or fails
                    Plan schema validation.
    """
    stripped = content.strip()
    m = _CODE_FENCE_RE.match(stripped)
    if m:
        stripped = m.group(1).strip()

    parsed: Any = json.loads(stripped)
    return Plan.model_validate(parsed)


# ---------------------------------------------------------------------------
# v0.9 prompt template (chat mode)
# ---------------------------------------------------------------------------

_PLANNER_PROMPT_TEMPLATE = """\
你是金融研究助手 chat 模式的 planner。决定本轮要做什么。

可用工具(只能从这里选,不要编):
{tool_descriptions}

用户当前问题:
{user_message}

历史摘要(如有):
{history_summary}

最近 {recent_k} 轮:
{recent_turns}

任务:
1. 决定是否调工具。如果用户问的问题需要数据,选合适的工具。
2. 如果可并行(无依赖),设 parallelizable=true。
3. 如果用户在请求"深度报告 / 完整尽调 / 详细分析"这类长程任务,设 escalate_offered=true 并给 reason。
4. 如果只是闲聊或简单问答,设 direct_response=true,tool_calls 留空。

严格按下列 JSON 输出,不要带任何额外文字:
{{
  "tool_calls": [{{"tool_name": "...", "args": {{...}}, "rationale": "..."}}, ...],
  "parallelizable": true|false,
  "direct_response": true|false,
  "escalate_offered": true|false,
  "escalate_reason": "..." or null,
  "reasoning": "<一句话摘要>"
}}
"""


# ---------------------------------------------------------------------------
# ChatPlanner — v0.9 primary class
# ---------------------------------------------------------------------------


class ChatPlanner(Agent):
    """Supervisor-style planner for v0.9 chat mode.

    v0.9 constructor (used by chat graph):
        ChatPlanner(llm, available_tools=[...])
        → async run(ChatState) -> dict[str, Any]

    Legacy constructor (research-mode graph, backwards-compat):
        ChatPlanner(llm, registry=ToolRegistry)
        → step(GraphState) -> StepResult
    """

    name = "ChatPlanner"
    model_tier: Tier = "balanced"

    def __init__(
        self,
        llm: LLMService,
        registry: ToolRegistry | None = None,
        available_tools: list[str] | None = None,
        recent_k: int = 4,
    ) -> None:
        super().__init__(llm)
        self._registry = registry
        self._available_tools = available_tools or []
        self._recent_k = recent_k

    # ------------------------------------------------------------------
    # v0.9 async interface (chat mode)
    # ------------------------------------------------------------------

    async def run(self, state: ChatState) -> dict[str, Any]:
        """Plan one chat turn: call LLM, filter hallucinated tools, emit Plan."""
        prompt = self._build_chat_prompt(state)
        resp = self._llm.chat(prompt=prompt, tier="balanced", schema=None)

        try:
            data = json.loads(resp.content)
        except json.JSONDecodeError:
            logger.warning("planner LLM returned non-JSON; defaulting to direct_response")
            return {
                "plan": Plan(
                    tool_calls=[],
                    direct_response=True,
                    reasoning="LLM 输出非 JSON，回退到 direct_response",
                ),
            }

        # A4: filter hallucinated tool names against whitelist
        whitelist = set(self._available_tools)
        valid_calls: list[ToolCall] = []
        for tc in data.get("tool_calls", []):
            tool_name = tc.get("tool_name", "")
            if not whitelist or tool_name in whitelist:
                valid_calls.append(
                    ToolCall(
                        tool_name=tool_name,
                        args=tc.get("args", {}),
                        rationale=tc.get("rationale", ""),
                    )
                )
            else:
                logger.warning("planner hallucinated tool: %s; dropping", tool_name)

        direct_response = bool(data.get("direct_response", False))
        escalate_offered = bool(data.get("escalate_offered", False))
        parallelizable = bool(data.get("parallelizable", False))
        reasoning = data.get("reasoning", "")

        # Build Plan — handle edge cases for validator:
        # - escalate_offered=True with no tool_calls: use direct_response=True
        # - tool_calls filtered to empty: force direct_response=True
        if not valid_calls and not direct_response:
            direct_response = True

        plan = Plan(
            tool_calls=valid_calls,
            direct_response=direct_response,
            reasoning=reasoning,
            parallelizable=parallelizable,
            escalate_offered=escalate_offered,
            escalate_reason=data.get("escalate_reason"),
        )

        return {
            "plan": plan,
            "escalate_offered": escalate_offered,
        }

    def _build_chat_prompt(self, state: ChatState) -> str:
        tool_lines = (
            [f"- {t}" for t in self._available_tools] if self._available_tools else ["(no tools)"]
        )
        recent = state.history[-self._recent_k :] if state.history else []
        recent_lines = [f"[{m.turn_index}] {m.role}: {m.content[:200]}" for m in recent]
        return _PLANNER_PROMPT_TEMPLATE.format(
            tool_descriptions="\n".join(tool_lines),
            user_message=state.user_message,
            history_summary=state.history_summary or "(无)",
            recent_k=self._recent_k,
            recent_turns="\n".join(recent_lines) or "(无)",
        )

    # ------------------------------------------------------------------
    # Legacy v0 sync interface (research-mode graph)
    # ------------------------------------------------------------------

    def step(self, state: GraphState) -> StepResult:
        """Build a planner prompt, call LLM, parse the returned Plan JSON.

        Legacy research-mode path — requires self._registry to be set.
        """
        if self._registry is None:
            raise RuntimeError(
                "ChatPlanner.step() requires registry=ToolRegistry; "
                "use run(ChatState) for v0.9 chat mode."
            )
        prompt = build_planner_prompt(state=state, registry=self._registry)
        r = self._llm.chat(
            prompt=prompt,
            tier=self.model_tier,
            request_id=state.request_id,
        )
        plan = _parse_plan(r.content)
        return StepResult(
            state_update={"plan": plan},
            span_metadata={
                "agent": "ChatPlanner",
                "model": r.model,
                "cost_cny": r.cost_cny,
            },
        )
