"""ChatPlanner — first LangGraph agent: decides which tools (if any) to call.

Path B (prompt-engineered JSON) per Task 0 Spike 1 retrospective:
- Build a prompt that lists available tools in human-readable markdown
- Include the user message
- Instruct LLM to output a JSON object matching the ``Plan`` schema
- ``_parse_plan`` strips code fences and Pydantic-validates the JSON

This intentionally does NOT add a ``tools=`` parameter to LLMService;
the LLMService.chat(prompt, tier, schema) contract stays stable.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.agents.base import Agent
from app.agents.schemas import GraphState, Plan, StepResult
from app.services.llm_response import Tier
from app.services.llm_service import LLMService
from app.tools.registry import ToolRegistry

# Regex to strip markdown code fences (```json ... ``` or ``` ... ```)
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)

# Prompt template pieces
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


class ChatPlanner(Agent):
    """Decide which tools to call (or respond directly) for a user message.

    Uses prompt-engineered JSON (Path B) — the LLM is asked to output a
    JSON object matching the Plan schema. No openai tool-calling is used.
    """

    name = "ChatPlanner"
    model_tier: Tier = "balanced"

    def __init__(self, llm: LLMService, registry: ToolRegistry) -> None:
        super().__init__(llm)
        self._registry = registry

    def step(self, state: GraphState) -> StepResult:
        """Build a planner prompt, call LLM, parse the returned Plan JSON."""
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
