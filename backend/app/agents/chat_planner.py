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
from app.agents.schemas import ChatState, GraphState, Plan, SkillScriptCall, StepResult, ToolCall
from app.memory.protocol import Memory
from app.services.llm_response import Tier
from app.services.llm_service import LLMService
from app.skills import SkillManifest
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# Regex to strip markdown code fences (```json ... ``` or ``` ... ```)
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)


# ---------------------------------------------------------------------------
# v0.9 skill list block (S2: L1 skill signal for ChatPlanner system prompt)
# ---------------------------------------------------------------------------


def build_skill_list_block(skills: list[SkillManifest]) -> str:
    """Render the L1 skill list as a markdown block for the planner system prompt.

    Format:
        ## Available Skills

        - **risk_assessment**: Investment risk assessment.
        - **financial_analysis**: ...

        To expand a skill, emit {"action": "load_skill", "name": "<n>"}.
        To load a specific resource within a loaded skill, emit
        {"action": "load_resource", "skill": "<n>", "ref": "resources/<file>"}.

    S2: this is the only signal the planner has about each skill's capability.
    Sorted by name for deterministic ordering. Empty input returns empty string.
    """
    if not skills:
        return ""

    lines = ["## Available Skills", ""]
    for s in sorted(skills, key=lambda x: x.name):
        desc = s.description.replace("\n", " ").strip()
        lines.append(f"- **{s.name}**: {desc}")
    lines.extend(
        [
            "",
            'To expand a skill, emit {"action": "load_skill", "name": "<n>"}.',
            "To load a specific resource within a loaded skill, emit "
            '{"action": "load_resource", "skill": "<n>", "ref": "resources/<file>"}.',
        ]
    )
    return "\n".join(lines)


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

# --------------------------------------------------------------------------
# Plan 6 (c5) — Memory vs KB routing prompt segregation
# spec § 11 末尾 #7 (c): 两路结果 prompt 显式区隔 [用户上下文] vs [市场知识]
# --------------------------------------------------------------------------

_USER_CONTEXT_HEADER = "[用户上下文]  ← 来自用户私人记忆,只用作偏好/持仓背景,不是投资结论"
_MARKET_KNOWLEDGE_HEADER = (
    "[市场知识]  ← 来自公开知识库(研报/财报/政策/新闻),客观信息,跟用户偏好独立"
)
_SEGREGATION_DISCLAIMER = (
    "\n注意: [用户上下文] 是用户的个人事实(持仓/偏好/历史想法),[市场知识] 是公开信息。"
    "回答时请区分,不要把它们混淆 — 比如 用户偏好白马 + 市场跑输大盘 是 trade-off,不是矛盾。\n"
)


def _format_memory_hits(hits: list[dict[str, Any]]) -> str:
    """Render memory hits into a compact user-context block.

    Top-5 truncation 防爆;每个 hit 渲染为单行 ``- {rel}: {ts_code}(valid_from=...)``
    或 fallback dump properties。
    """
    if not hits:
        return ""
    lines = [_USER_CONTEXT_HEADER]
    for h in hits[:5]:  # 防爆
        rel = h.get("rel_type", "?")
        props = h.get("properties", {}) or {}
        valid_from = h.get("valid_from", "?")
        ts_code = props.get("ts_code") or props.get("label") or ""
        if ts_code:
            lines.append(f"- {rel}: {ts_code}(valid_from={valid_from})")
        else:
            lines.append(f"- {rel}: {props}(valid_from={valid_from})")
    return "\n".join(lines)


def _format_kb_hits(hits: list[dict[str, Any]]) -> str:
    """Render kb hits into a compact market-knowledge block.

    Top-5 truncation + 240 char chunk_text 截断。
    """
    if not hits:
        return ""
    lines = [_MARKET_KNOWLEDGE_HEADER]
    for h in hits[:5]:
        text = str(h.get("chunk_text", ""))[:240]
        try:
            sim = float(h.get("similarity", 0.0))
        except (TypeError, ValueError):
            sim = 0.0
        meta = h.get("metadata", {}) or {}
        broker = meta.get("broker", "")
        broker_part = f", {broker}" if broker else ""
        lines.append(f"- (sim={sim:.2f}{broker_part}) {text}")
    return "\n".join(lines)


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
5. 如果用户问题需要某 skill 的细节(SKILL.md 全文),设 load_skill="<skill_name>"。
6. 如果你已经看过 SKILL.md,需要里面引用的具体 resource,设 load_resource={{"skill": "<n>", "ref": "resources/<file>"}}。
   注意: load_skill / load_resource / tool_calls 三选一,不要同时设置多个。
7. 如果某 skill 提供脚本能完成用户的计算需求(如 DCF 估值、风险打分等),优先用 script_calls。
   script_calls 格式: [{{"skill": "<skill_name>", "script": "scripts/<file>.py", "args": {{...}}}}]
   每个 entry 的 script 字段必须以 "scripts/" 开头。

严格按下列 JSON 输出,不要带任何额外文字:
{{
  "tool_calls": [{{"tool_name": "...", "args": {{...}}, "rationale": "..."}}, ...],
  "script_calls": [{{"skill": "...", "script": "scripts/...", "args": {{...}}}}],
  "parallelizable": true|false,
  "direct_response": true|false,
  "escalate_offered": true|false,
  "escalate_reason": "..." or null,
  "reasoning": "<一句话摘要>",
  "load_skill": "..." or null,
  "load_resource": {{"skill": "...", "ref": "..."}} or null
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
        available_skills: list[str] | None = None,
        recent_k: int = 4,
        memory: Memory | None = None,  # ← 新增, Phase 1 self-managed wire
    ) -> None:
        super().__init__(llm)
        self._registry = registry
        self._available_tools = available_tools or []
        self._available_skills = available_skills or []
        self._recent_k = recent_k
        self._memory = memory  # ← 新增

    # ------------------------------------------------------------------
    # v0.9 async interface (chat mode)
    # ------------------------------------------------------------------

    async def run(self, state: ChatState) -> dict[str, Any]:
        """Plan one chat turn: call LLM, filter hallucinated tools, emit Plan."""
        prompt = await self._build_chat_prompt(state)
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

        # Plan 2a: parse new skill action fields
        raw_load_skill = data.get("load_skill")
        load_skill = raw_load_skill if isinstance(raw_load_skill, str) else None
        raw_load_resource = data.get("load_resource")
        load_resource = raw_load_resource if isinstance(raw_load_resource, dict) else None

        # Plan 2b: parse execute_script actions (whitelist by available_skills)
        whitelist_skills = set(self._available_skills)
        valid_script_calls: list[SkillScriptCall] = [
            SkillScriptCall(
                skill=sc["skill"],
                script=sc["script"],
                args=sc.get("args", {}),
            )
            for sc in data.get("script_calls", [])
            if sc.get("skill") in whitelist_skills and sc.get("script", "").startswith("scripts/")
        ]

        # Build Plan — handle edge cases for validator:
        # - escalate_offered=True with no tool_calls: use direct_response=True
        # - tool_calls filtered to empty and no skill action: force direct_response=True
        has_action = (
            bool(valid_calls)
            or escalate_offered
            or load_skill
            or load_resource
            or bool(valid_script_calls)
        )
        if not has_action and not direct_response:
            direct_response = True

        plan = Plan(
            tool_calls=valid_calls,
            direct_response=direct_response,
            reasoning=reasoning,
            parallelizable=parallelizable,
            escalate_offered=escalate_offered,
            escalate_reason=data.get("escalate_reason"),
            load_skill=load_skill,
            load_resource=load_resource,
            script_calls=valid_script_calls,
        )

        return {
            "plan": plan,
            "escalate_offered": escalate_offered,
        }

    async def _build_chat_prompt(self, state: ChatState) -> str:
        # Tool descriptions: prefer registry full schema (name + description + JSON Schema)
        # so the LLM emits args matching each tool's args_schema exactly. Fallback to
        # bare name list when registry is absent (legacy callers).
        tool_lines: list[str]
        if self._registry is not None:
            schemas = self._registry.list_for_llm()
            if self._available_tools:
                whitelist = set(self._available_tools)
                schemas = [s for s in schemas if s["function"]["name"] in whitelist]
            if schemas:
                tool_lines = [
                    f"- {s['function']['name']}: {s['function']['description']}\n"
                    f"  parameters (JSON Schema): "
                    f"{json.dumps(s['function']['parameters'], ensure_ascii=False)}"
                    for s in schemas
                ]
            else:
                tool_lines = ["(no tools)"]
        elif self._available_tools:
            tool_lines = [f"- {t}" for t in self._available_tools]
        else:
            tool_lines = ["(no tools)"]
        recent = state.history[-self._recent_k :] if state.history else []
        recent_lines = [f"[{m.turn_index}] {m.role}: {m.content[:200]}" for m in recent]
        prompt = _PLANNER_PROMPT_TEMPLATE.format(
            tool_descriptions="\n".join(tool_lines),
            user_message=state.user_message,
            history_summary=state.history_summary or "(无)",
            recent_k=self._recent_k,
            recent_turns="\n".join(recent_lines) or "(无)",
        )

        # === Plan 6 (c5) — segregation blocks injection ===
        # spec § 11 末尾 #7 (c): 两路结果 prompt 显式区隔 [用户上下文] vs [市场知识]
        user_ctx_block = _format_memory_hits(state.memory_hits)
        market_block = _format_kb_hits(state.kb_hits)

        if user_ctx_block or market_block:
            inject_parts: list[str] = []
            if user_ctx_block:
                inject_parts.append(user_ctx_block)
            if market_block:
                inject_parts.append(market_block)
            if user_ctx_block and market_block:
                inject_parts.append(_SEGREGATION_DISCLAIMER)
            inject_block = "\n\n".join(inject_parts) + "\n\n"
            # Insert before "用户当前问题:" anchor — 最显眼位置
            anchor = "用户当前问题:"
            prompt = prompt.replace(anchor, inject_block + anchor, 1)

        # === Phase 1 (chat-memory-layering) — self-managed wire ===
        # spec § 7 Phase 1: memory_tool_usage prompt prepend 到主 prompt 头部
        if self._memory is not None:
            try:
                from uuid import UUID

                from app.agents.chat.prompt_loader import (
                    load_memory_tool_usage_prompt,
                )

                memory_block = await load_memory_tool_usage_prompt(
                    memory=self._memory,
                    user_id=UUID(state.user_id),
                    session_id=UUID(state.session_id),
                )
                prompt = memory_block + "\n\n---\n\n" + prompt
            except Exception as exc:  # noqa: BLE001 — chat 不崩 fail-safe
                logger.warning("memory_tool_usage prompt injection failed: %s", exc)

        return prompt

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
