"""SUT-runner —— 跑真 ChatLoopAgent,产出每 case 的 SUTOutput 投影。

修了现有 ``eval.tool_selection._live_deps.build_eval_singletons`` 的 latent bug:
那里手动 ``await mcp_ctx.__aenter__()`` 把 MCP subprocess 上下文跨任务泄漏,anyio 抛
``RuntimeError: Attempted to exit cancel scope in a different task``,连首次 LLM 调用
都被 cancel。**修法**:用 ``async with MCPClient.from_subprocess(...)`` 把 singletons
构造 + 整个 case 循环包在同一任务里(本文件 run_scenarios)。

dispatch 两模式:
- ``noop``(行为①②③ + 免责):FakeNoopHub —— schema 透传真件,dispatch 占位,
  首轮工具选择即 SUTOutput.tool_calls;max_steps=1(序列 case=2)。
- ``real``(行为④ grounding):真 ToolHub —— agent 真检索真答,max_steps=6。

k>1:同 case 跑 k 次(独立 request_id),供 pass^k。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from eval.chatloop.scenario import Scenario

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SutResult:
    case_id: str
    run_idx: int
    tool_calls: list[dict[str, Any]]
    response_text: str
    escalate_offered: bool
    error: str | None = None


async def run_scenarios(
    scenarios: list[Scenario],
    *,
    dispatch_mode: str = "noop",
    k: int = 1,
    max_steps: int | None = None,
) -> list[SutResult]:
    """构造真件,跑全部 scenarios × k 次,返回 SutResult 列表(per-case 错误隔离)。"""
    # 延迟 import:dry / 单测路径零重依赖(无 PG/MCP/LLM)。
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.app_main import _sqlalchemy_async_pg_url
    from app.chatloop.context import ContextDeps
    from app.chatloop.eval_agent import ChatLoopAgent
    from app.chatloop.gates import GateConfig
    from app.chatloop.system_prompt import CHAT_SYSTEM_PROMPT
    from app.chatloop.worker_wiring import build_heavy_singletons
    from app.services.mcp_client import MCPClient
    from eval.tool_selection._live import FakeNoopHub, build_real_hub

    engine = create_async_engine(_sqlalchemy_async_pg_url(), future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    results: list[SutResult] = []

    try:
        # 关键:async with 把 MCP 上下文 + singletons + case 循环锁在同一任务(修 cancel-scope bug)
        async with MCPClient.from_subprocess(profile="chat_tools") as mcp_client:
            singletons = await build_heavy_singletons(
                session_factory=session_factory,
                mcp_client=mcp_client,
            )
            deps = ContextDeps(
                system_prompt=CHAT_SYSTEM_PROMPT,
                skill_listing=singletons.skill_listing,
            )
            for sc in scenarios:
                is_seq = "tools_sequence_contains" in sc.expected
                if dispatch_mode == "real":
                    steps = max_steps or 6
                else:
                    steps = max_steps or (2 if is_seq else 1)
                for run_idx in range(k):
                    rid = f"clev-{sc.case_id}-{run_idx}"
                    try:
                        real_hub = build_real_hub(singletons)
                        hub: Any = (
                            real_hub
                            if dispatch_mode == "real"
                            else FakeNoopHub(real_hub, run_search_tools_live=is_seq)
                        )
                        agent = ChatLoopAgent(
                            llm=singletons.llm,
                            tool_hub=hub,
                            context_deps=deps,
                            gate_cfg=GateConfig(max_steps=steps),
                        )
                        out = await agent.run(sc.user_input, rid)
                        results.append(
                            SutResult(
                                case_id=sc.case_id,
                                run_idx=run_idx,
                                tool_calls=[
                                    {"tool_name": tc.tool_name, "args": tc.args}
                                    for tc in out.tool_calls
                                ],
                                response_text=out.response_text,
                                escalate_offered=out.escalate_offered,
                            )
                        )
                    except Exception as e:  # noqa: BLE001 — per-case 隔离,fail loud 但不炸整跑
                        logger.exception("case %s run %d 失败", sc.case_id, run_idx)
                        results.append(
                            SutResult(
                                case_id=sc.case_id,
                                run_idx=run_idx,
                                tool_calls=[],
                                response_text="",
                                escalate_offered=False,
                                error=f"{type(e).__name__}: {e}",
                            )
                        )
    finally:
        await engine.dispose()

    return results


__all__ = ["SutResult", "run_scenarios"]
