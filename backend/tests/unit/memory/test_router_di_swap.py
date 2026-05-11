"""L0 smoke: chat router _build_graph_singleton DI 替换为 HierarchicalMemory.

由于 _build_graph_singleton 真起 LLM client / Tushare client(env-driven),
本 smoke test 仅验证 import path + memory 类型, 不真跑 graph.

注: 真完整 DI 测试在 Task 10 的 manual smoke step.
"""

from __future__ import annotations

import inspect


def test_chat_router_imports_hierarchical_memory() -> None:
    """chat router 不再 import InSessionMemory 主路径, 改 import HierarchicalMemory."""
    import app.router.chat as chat_router_module

    src = inspect.getsource(chat_router_module._build_graph_singleton)
    assert "HierarchicalMemory" in src, (
        "chat router _build_graph_singleton 必须 import + 实例化 HierarchicalMemory"
    )
    # InSessionMemory legacy import 可以仍留(Q4 E in-session dedup / summarize 仍需)
    # 但 Memory Protocol 注入到 graph 的应是 HierarchicalMemory


def test_hierarchical_memory_satisfies_protocol_at_import() -> None:
    """sanity: HierarchicalMemory 在 import time satisfies Protocol."""
    from app.memory.hierarchical import HierarchicalMemory
    from app.memory.protocol import Memory

    instance = HierarchicalMemory(
        pg_session_factory=None,
        age_executor=None,
        milvus_client=None,
        embed_service=None,
        llm_extractor=None,
        llm_judge=None,
    )
    assert isinstance(instance, Memory)
