"""chatloop worker 组装 —— 把 ToolLoop 全部依赖构造收口一处(Phase 4 Task 4.2)。

chat_runner 的 run_chat_async 因此能瘦下来:只管 turn 生命周期(mark_running /
rebuild / 事件发射 / finalize),不管"怎么造 LLM / registry / memory / 工具表"。

singleton vs per-turn 拆分(重要):
- emit / seq_counter 是 **per-turn** 的(每个 task 一个 SeqCounter + 一个 XADD 闭包),
  所以 ToolHub(持 emit/seq_counter)不能做纯进程单例;
- 但重依赖(LLMService / ToolRegistry+MCP / HierarchicalMemory / SkillLoader /
  SkillExecutor / ToolResultCache)起一次很贵,必须进程级单例。

故拆两层:
  build_heavy_singletons()  —— worker 进程首个 task 时构造一次,缓存复用(重依赖);
  build_turn_hub(singletons, emit, seq_counter)  —— 每 turn 构造一个轻 ToolHub
                                                    (只是工具表 + emit/seq 引用)。

RedisSteerSource 也在本模块:圈边界 RPOP 全部 pending 插话(spec § 4.3,List 不用
pub/sub)。本任务实现读端;写端(POST /chat/steer)是 Task 4.3。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.chatloop.code_interpreter_tool import CodeInterpreterTool
from app.chatloop.control_tools import OfferDeepResearchTool, ReadCachedResultTool
from app.chatloop.events import SeqCounter
from app.chatloop.gates import GateConfig
from app.chatloop.memory_tools import MemorySearchTool, MemoryWriteTool
from app.chatloop.portfolio_tool import GetPortfolioPositionsTool
from app.chatloop.skill_listing import build_skill_listing
from app.chatloop.skill_tools import LoadSkillTool, RunSkillScriptTool
from app.chatloop.subagent import DispatchSubagentsTool, SubagentFactory
from app.chatloop.system_prompt import CHAT_SYSTEM_PROMPT
from app.chatloop.tool_hub import EmitFn, ToolHub
from app.memory.injection_classifier import is_prompt_injection
from app.services.chat_steer_bus import steer_key
from app.services.subagent_audit import SubagentAuditRepo
from app.services.tool_result_cache import ToolResultCache
from app.skills.executor_backend import SkillExecutorBackend

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 模块级常量:chat 技能目录(供测试及 _live_deps 等导入,避免路径重复声明)
# ---------------------------------------------------------------------------
from pathlib import Path as _Path

# chat 模式 7 技能集目录:backend/claude_skills
CHAT_SKILLS_ROOT: _Path = _Path(__file__).resolve().parent.parent.parent / "claude_skills"

# ---------------------------------------------------------------------------
# 重依赖单例容器
# ---------------------------------------------------------------------------


@dataclass
class HeavySingletons:
    """worker 进程级单例 —— 起一次复用。turn 间不变。"""

    llm: Any  # LLMService(.stream_step + .chat)
    registry: Any  # ToolRegistry(已 register MCP chat_tools profile)
    memory: Any  # HierarchicalMemory
    loader: Any  # SkillLoader
    executor: Any  # SkillExecutor
    cache: ToolResultCache
    skill_listing: str  # L1 元数据清单(进稳定前缀,会话内冻结)
    gate_cfg: GateConfig
    session_factory: Any = None  # async_sessionmaker —— get_portfolio_positions 查 positions 用
    trace: Any = None  # TraceService —— ToolHub 写工具 span 用


@dataclass
class ChatLoopComponents:
    """build_chat_loop_components 的产物(本任务对外契约形状)。

    spec 计划里给的 dataclass 字段:llm / tool_hub / gate_cfg / skill_listing /
    system_prompt。tool_hub 是 per-turn 的,故本结构由 build_turn_components 产出
    (持已造好的 ToolHub)。
    """

    llm: Any
    tool_hub: ToolHub
    gate_cfg: GateConfig
    skill_listing: str
    system_prompt: str
    memory: Any  # runner 需要它造 episode_id_resolver / persona render


# ---------------------------------------------------------------------------
# 单例构造(重依赖)
# ---------------------------------------------------------------------------


async def build_heavy_singletons(
    *,
    session_factory: Any,
    mcp_client: Any,
    llm: Any | None = None,
    memory: Any | None = None,
    skills_root: Any | None = None,
    workdir_root: Any | None = None,
) -> HeavySingletons:
    """构造 worker 进程级重依赖(spec § 3 接线)。

    测试缝:llm / memory 可被注入覆盖(ScriptedStepClient / Fake memory),
    其余(registry/loader/executor/cache)走真实构造但接受 None mcp_client 时
    registry 为空表(纯 in-process 工具仍可用)。

    Args:
        session_factory: async_sessionmaker —— ToolResultCache + memory 共用。
        mcp_client: 已 __aenter__ 的 MCPClient(chat_tools profile);None → 跳过 MCP 注册。
        llm: 覆盖 LLMService(测试注入)。
        memory: 覆盖 HierarchicalMemory(测试注入)。
        skills_root / workdir_root: 覆盖技能目录(测试注入 tmp dir)。
    """
    from pathlib import Path

    # 1. LLM
    if llm is None:
        from app.services.openai_client import build_llm_service_from_env

        llm = build_llm_service_from_env()

    # 2. ToolRegistry + MCP(沿用 chat.py._build_graph_singleton 的注册模式)
    from app.tools.registry import ToolRegistry

    registry = ToolRegistry()
    if mcp_client is not None:
        await registry.register_mcp_client_async(mcp_client)

    # 3. HierarchicalMemory(worker 模式;沿用 _common.build_memory_from_env 口径)
    if memory is None:
        from app.mcp_server.tools.memory._common import build_memory_from_env

        memory = build_memory_from_env()

    # 4. SkillLoader / SkillExecutor
    #    目录分工:
    #      backend/claude_skills  — chat 模式 7 技能集(data_analysis / deep_research /
    #                               financial_analysis / market_data / risk_assessment /
    #                               sector_analysis / web_research),SkillLoader 兼容格式;
    #      backend/app/skills     — v0.8.5 深研 SOP 技能(financial_research + 框架代码),
    #                               由 SkillBundle / load_skill 独立加载,不走 SkillLoader。
    from app.skills.skill_executor import SkillExecutor
    from app.skills.skill_loader import SkillLoader

    if skills_root is None:
        # backend/claude_skills —— 本模块在 backend/app/chatloop 下:
        #   Path(__file__).parent = backend/app/chatloop
        #   .parent               = backend/app
        #   .parent               = backend
        #   / "claude_skills"     = backend/claude_skills
        skills_root = Path(__file__).resolve().parent.parent.parent / "claude_skills"
    skills_root = Path(skills_root)
    if workdir_root is None:
        workdir_root = skills_root.parent / ".skill_workdirs"
    loader = SkillLoader(skills_root=skills_root)
    executor = SkillExecutor(skills_root=skills_root, workdir_root=workdir_root)

    # 5. ToolResultCache(PG-backed,get_raw 取回源)
    cache = ToolResultCache(session_factory)

    # 6. 技能清单(L1 元数据,进稳定前缀;loader 目录不存在则空清单标题)
    try:
        skill_listing = build_skill_listing(loader)
    except Exception as exc:  # noqa: BLE001 — 清单构造失败降级为空标题,不阻塞 turn
        logger.warning("build_skill_listing 失败,降级空清单: %s", exc)
        skill_listing = "## 可用技能"

    # TraceService —— ToolHub 写工具 span(与 LLM span 落同一张 trace_spans 表)
    from app.core.database import SessionLocal
    from app.services.trace_service import TraceService

    trace = TraceService(SessionLocal)

    return HeavySingletons(
        llm=llm,
        registry=registry,
        memory=memory,
        loader=loader,
        executor=executor,
        cache=cache,
        skill_listing=skill_listing,
        gate_cfg=GateConfig(),
        session_factory=session_factory,
        trace=trace,
    )


# ---------------------------------------------------------------------------
# per-turn 构造(轻 ToolHub)
# ---------------------------------------------------------------------------


def build_turn_components(
    singletons: HeavySingletons,
    *,
    emit: EmitFn,
    seq_counter: SeqCounter,
    episode_id_resolver: Any | None = None,
) -> ChatLoopComponents:
    """per-turn 构造轻 ToolHub —— 把单例依赖塞进新 hub(持 turn 级 emit/seq)。

    episode_id_resolver:Phase 4 worker 在 turn 开头 write_episode 后注入一个返回本
    turn episode_id 的 resolver(memory_tools 的 archival_insert 用)。本任务无现成
    "turn 开始建 episode"链路(见 chat_runner / 报告),传 None → MemoryWriteTool 用
    默认 resolver(archival_insert 返回指导错误而非静默丢;core_append/replace 不受影响)。
    """
    hub = ToolHub(
        emit=emit, cache=singletons.cache, seq_counter=seq_counter, trace=singletons.trace
    )
    hub.register_registry(singletons.registry)

    memory_write_kwargs: dict[str, Any] = {
        "memory": singletons.memory,
        "injection_classifier": is_prompt_injection,
    }
    if episode_id_resolver is not None:
        memory_write_kwargs["episode_id_resolver"] = episode_id_resolver

    # 子 agent 派发 factory(per-turn:闭包持 turn 级 emit/seq_counter;
    # spawn 子循环复用同一 registry/cache,留痕走 SubagentAuditRepo)。
    subagent_factory = SubagentFactory(
        llm=singletons.llm,
        registry=singletons.registry,
        cache=singletons.cache,
        emit=emit,
        seq_counter=seq_counter,
        gate_cfg=singletons.gate_cfg,
        audit_repo=SubagentAuditRepo(),
    )

    hub.register_inprocess(
        [
            MemorySearchTool(memory=singletons.memory),
            MemoryWriteTool(**memory_write_kwargs),
            LoadSkillTool(loader=singletons.loader),
            RunSkillScriptTool(executor=singletons.executor),
            OfferDeepResearchTool(),
            ReadCachedResultTool(cache=singletons.cache),
            CodeInterpreterTool(
                backend=SkillExecutorBackend(singletons.executor), cache=singletons.cache
            ),
            DispatchSubagentsTool(factory=subagent_factory),
            GetPortfolioPositionsTool(session_factory=singletons.session_factory),
        ]
    )

    return ChatLoopComponents(
        llm=singletons.llm,
        tool_hub=hub,
        gate_cfg=singletons.gate_cfg,
        skill_listing=singletons.skill_listing,
        system_prompt=CHAT_SYSTEM_PROMPT,
        memory=singletons.memory,
    )


def build_run_executor(
    singletons: HeavySingletons,
    *,
    user_id: Any,
    event_sink: Any,
    cancel_event: Any,
    pause_controller: Any | None = None,
    provider: str = "unknown",
    model: str = "unknown",
    persona_block: str = "",
) -> Any:
    """Outer wiring boundary for the transport-free Run executor.

    The lazy import keeps ``run_executor`` independent of this module's heavy
    service/tool graph.  Its per-execution factory injects the same emitter and
    sequence counter into ToolLoop and ToolHub, preserving global event order.
    """

    from app.chatloop.run_executor import ChatRunExecutor

    return ChatRunExecutor(
        components_factory=lambda emit, seq_counter: build_turn_components(
            singletons,
            emit=emit,
            seq_counter=seq_counter,
        ),
        event_sink=event_sink,
        cancel_event=cancel_event,
        user_id=user_id,
        pause_controller=pause_controller,
        provider=provider,
        model=model,
        persona_block=persona_block,
    )


# ---------------------------------------------------------------------------
# RedisSteerSource(读端 — spec § 4.3 List RPOP)
# ---------------------------------------------------------------------------


class RedisSteerSource:
    """圈边界取插话:RPOP 循环把 List `chat:steer:{task_id}` 全部 pending 取出(FIFO)。

    写端 LPUSH(POST /chat/steer → ChatSteerBus.push)。用 RPOP 配 LPUSH = FIFO:
    先到的插话先被并入。空 List → []。key 经 ``steer_key`` 与写端共享单一来源。
    """

    def __init__(self, redis: Any, task_id: UUID | str) -> None:
        self._redis = redis
        self._key = steer_key(task_id)

    async def pop_all(self) -> list[str]:
        out: list[str] = []
        while True:
            raw = await self._redis.rpop(self._key)
            if raw is None:
                break
            out.append(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))
        return out


__all__ = [
    "CHAT_SKILLS_ROOT",
    "ChatLoopComponents",
    "HeavySingletons",
    "RedisSteerSource",
    "build_heavy_singletons",
    "build_run_executor",
    "build_turn_components",
]
