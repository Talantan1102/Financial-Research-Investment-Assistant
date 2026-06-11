"""--live 真件 wiring —— 构造 chatloop HeavySingletons(LLM + MCP + memory + skills)。

延迟 import:dry / 单测路径绝不 import 本模块(无 PG / MCP / LLM 依赖)。
与 ``app.tasks.chat_runner._build_singletons_for_worker`` 同款 wiring:
真 LLMService + MCPClient(chat_tools profile)+ HierarchicalMemory + SkillLoader/Executor。

仅 --live CLI 跑时调用(联调阶段);本任务不在 6.2 跑 --live。
"""

from __future__ import annotations

from typing import Any

# 防 GC 保活:from_subprocess 的 ctx 一旦出作用域被回收,其 MCP stdio asyncgen 会
# aclose() → athrow(GeneratorExit) 进挂在 yield 处的 anyio task group,取消在途协程
# (实测:build 返回后 ctx 被 GC,第一条 case 的 LLM 调用即被 cancel)。与
# chat_runner._MCP_CTX_SINGLETON 同款"keep ctx ref alive — GC would tear down subprocess"。
_MCP_CTX_KEEPALIVE: Any | None = None


async def build_eval_singletons() -> Any:
    """构造评测用 HeavySingletons(真件)。Raises 若 LLM/PG/MCP 环境缺失(fail-loud)。"""
    from app.app_main import _sqlalchemy_async_pg_url
    from app.chatloop.worker_wiring import build_heavy_singletons
    from app.services.mcp_client import MCPClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    global _MCP_CTX_KEEPALIVE

    engine = create_async_engine(_sqlalchemy_async_pg_url(), future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    mcp_ctx = MCPClient.from_subprocess(profile="chat_tools")
    _MCP_CTX_KEEPALIVE = (
        mcp_ctx  # 保活:别让 ctx 出作用域被 GC(否则 MCP asyncgen aclose 取消在途协程)
    )
    mcp_client = await mcp_ctx.__aenter__()

    return await build_heavy_singletons(
        session_factory=session_factory,
        mcp_client=mcp_client,
    )
