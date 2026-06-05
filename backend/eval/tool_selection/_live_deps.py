"""--live 真件 wiring —— 构造 chatloop HeavySingletons(LLM + MCP + memory + skills)。

延迟 import:dry / 单测路径绝不 import 本模块(无 PG / MCP / LLM 依赖)。
与 ``app.tasks.chat_runner._build_singletons_for_worker`` 同款 wiring:
真 LLMService + MCPClient(chat_tools profile)+ HierarchicalMemory + SkillLoader/Executor。

仅 --live CLI 跑时调用(联调阶段);本任务不在 6.2 跑 --live。
"""
from __future__ import annotations

from typing import Any


async def build_eval_singletons() -> Any:
    """构造评测用 HeavySingletons(真件)。Raises 若 LLM/PG/MCP 环境缺失(fail-loud)。"""
    from app.app_main import _sqlalchemy_async_pg_url
    from app.chatloop.worker_wiring import build_heavy_singletons
    from app.services.mcp_client import MCPClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(_sqlalchemy_async_pg_url(), future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    mcp_ctx = MCPClient.from_subprocess(profile="chat_tools")
    mcp_client = await mcp_ctx.__aenter__()

    return await build_heavy_singletons(
        session_factory=session_factory,
        mcp_client=mcp_client,
    )
