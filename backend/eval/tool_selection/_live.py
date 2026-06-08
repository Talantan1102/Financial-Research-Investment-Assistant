"""--live 模式:构造真件 ChatLoopAgent + FakeNoopHub,跑首轮工具选择。

设计(spec § 5.2 + 任务说明):评测只看模型的**第一轮选择**,工具不真跑。
- schema 用真件:FakeNoopHub 内嵌一个真 ToolHub(注册全部 in-process + 真 tool_docs
  分组),``schemas_for_llm()`` 透传 —— 模型看到的工具表与生产逐字一致,选择行为才可信;
- dispatch 用 noop:返回 success=True 的空结果占位,模型拿到"已成功"就不会因报错改道,
  我们也不付真实工具调用的成本/时延;
- 例外:tools_sequence 类 case 用 max_steps=2,且 dispatch 对 ``search_tools`` **真跑**
  (本地确定性纯函数,无副作用)—— 让模型先检索到目标工具文档,再在第二圈选目标工具。

成本标注:--live 跑一次整套 golden ≈ 45+ 次 LLM 调用(普通 case 1 圈 + 序列 case 2 圈)。
本模式不在 Task 6.2 跑(联调阶段由控制器跑);本任务只保证 dry 模式 + 单测绿。
"""

from __future__ import annotations

from typing import Any

from app.agents.schemas import ToolResult
from app.chatloop.context import ContextDeps
from app.chatloop.control_tools import OfferDeepResearchTool, ReadCachedResultTool
from app.chatloop.eval_agent import ChatLoopAgent
from app.chatloop.gates import GateConfig
from app.chatloop.state import ChatLoopState
from app.chatloop.system_prompt import CHAT_SYSTEM_PROMPT
from app.chatloop.tool_hub import SEARCH_TOOLS_NAME, ToolHub
from app.services.llm_step import StepToolCall

from eval.tool_selection._core import GoldenCase


class FakeNoopHub:
    """包真 ToolHub —— schema 透传真件,dispatch 改 noop(search_tools 可选真跑)。

    满足 ToolHubProtocol(schemas_for_llm + dispatch)。run_search_tools_live=True 时,
    search_tools 调用委派给内嵌真 hub(让序列 case 能拿到检索结果),其余工具一律
    返回 success=True 的空占位结果(模型据此认为调用成功,不改道)。
    """

    def __init__(self, real_hub: ToolHub, *, run_search_tools_live: bool = False) -> None:
        self._real = real_hub
        self._run_search = run_search_tools_live

    def schemas_for_llm(self) -> list[dict[str, Any]]:
        return self._real.schemas_for_llm()

    async def dispatch(self, calls: list[StepToolCall], state: ChatLoopState) -> list[ToolResult]:
        results: list[ToolResult] = []
        for call in calls:
            if call.name == SEARCH_TOOLS_NAME and self._run_search:
                # 真跑 search_tools(确定性纯函数,无副作用)— 委派内嵌真 hub
                real_results = await self._real.dispatch([call], state)
                results.extend(real_results)
                continue
            try:
                args = call.parsed_args
            except ValueError:
                args = {}
            results.append(
                ToolResult(
                    tool_name=call.name,
                    args=args,
                    success=True,
                    output={"note": "[eval-noop] 占位结果,工具未真跑"},
                    latency_ms=0,
                )
            )
        return results


def build_real_hub(singletons: Any) -> ToolHub:
    """用 HeavySingletons 造一个真 ToolHub(全工具表 + 真 tool_docs schema)。

    与 worker_wiring.build_turn_components 同款注册:registry(MCP)+ 6 个 in-process。
    emit=None(评测不发 SSE)。
    """
    from app.chatloop.memory_tools import MemorySearchTool, MemoryWriteTool
    from app.chatloop.skill_tools import LoadSkillTool, RunSkillScriptTool
    from app.memory.injection_classifier import is_prompt_injection

    hub = ToolHub(emit=None, cache=singletons.cache)
    hub.register_registry(singletons.registry)
    hub.register_inprocess(
        [
            MemorySearchTool(memory=singletons.memory),
            MemoryWriteTool(memory=singletons.memory, injection_classifier=is_prompt_injection),
            LoadSkillTool(loader=singletons.loader),
            RunSkillScriptTool(executor=singletons.executor),
            OfferDeepResearchTool(),
            ReadCachedResultTool(cache=singletons.cache),
        ]
    )
    return hub


async def run_case_live(case: GoldenCase, singletons: Any, request_id: str) -> list[dict[str, Any]]:
    """跑单 case 的首轮选择,返回 [{"tool_name", "args"}, ...](已排除 search_tools)。

    - 序列 case(expected 含 tools_sequence_contains):max_steps=2 + search_tools 真跑;
    - 普通 case:max_steps=1,跑一圈即停。
    """
    is_seq = "tools_sequence_contains" in case.expected
    real_hub = build_real_hub(singletons)
    hub = FakeNoopHub(real_hub, run_search_tools_live=is_seq)
    gate_cfg = GateConfig(max_steps=2 if is_seq else 1)

    deps = ContextDeps(
        system_prompt=CHAT_SYSTEM_PROMPT,
        skill_listing=singletons.skill_listing,
    )
    agent = ChatLoopAgent(
        llm=singletons.llm,
        tool_hub=hub,
        context_deps=deps,
        gate_cfg=gate_cfg,
    )
    out = await agent.run(case.user_input, request_id)
    return [{"tool_name": tc.tool_name, "args": tc.args} for tc in out.tool_calls]
