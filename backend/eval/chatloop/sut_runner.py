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

# 评测固定 user_id —— 必须是合法 UUID(memory_search 等按 UUID 解析;"eval" 会炸)。
_EVAL_USER_ID = "00000000-0000-4000-8000-000000000001"


@dataclass(frozen=True)
class SutResult:
    case_id: str
    run_idx: int
    tool_calls: list[dict[str, Any]]
    response_text: str
    escalate_offered: bool
    evidence: str = ""  # real dispatch:agent 看到的工具返回(grounding 判依据)
    error: str | None = None


async def run_scenarios(
    scenarios: list[Scenario],
    *,
    dispatch_mode: str = "noop",
    k: int = 1,
    max_steps: int | None = None,
    system_prompt: str | None = None,
) -> list[SutResult]:
    """构造真件,跑全部 scenarios × k 次,返回 SutResult 列表(per-case 错误隔离)。

    system_prompt: 覆盖系统提示词(prompt 消融用,如对照"加免责前/后");None=生产 CHAT_SYSTEM_PROMPT。
    """
    # 延迟 import:dry / 单测路径零重依赖(无 PG/MCP/LLM)。
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.app_main import _sqlalchemy_async_pg_url
    from app.chatloop.context import ContextDeps
    from app.chatloop.eval_agent import ChatLoopAgent
    from app.chatloop.gates import GateConfig
    from app.chatloop.loop import ToolLoop
    from app.chatloop.state import ChatLoopState
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
                system_prompt=system_prompt or CHAT_SYSTEM_PROMPT,
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
                        # 直接跑 ToolLoop(而非 ChatLoopAgent.run)以保留 final 状态 → 抽 evidence
                        state = ChatLoopState(
                            user_id=_EVAL_USER_ID,
                            session_id=rid,
                            request_id=rid,
                            messages=[{"role": "user", "content": sc.user_input}],
                        )
                        toolloop = ToolLoop(
                            llm=singletons.llm,
                            tool_hub=hub,
                            context_deps=deps,
                            gate_cfg=GateConfig(max_steps=steps),
                        )
                        final = await toolloop.run(state)
                        resp = final.final_response or ChatLoopAgent._last_assistant_content(final)
                        tcs = ChatLoopAgent._extract_tool_calls(final)
                        evidence = "\n".join(
                            str(m.get("content", ""))
                            for m in final.messages
                            if m.get("role") == "tool"
                        )
                        results.append(
                            SutResult(
                                case_id=sc.case_id,
                                run_idx=run_idx,
                                tool_calls=[
                                    {"tool_name": tc.tool_name, "args": tc.args} for tc in tcs
                                ],
                                response_text=resp,
                                escalate_offered=final.escalate_offered,
                                evidence=evidence,
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
