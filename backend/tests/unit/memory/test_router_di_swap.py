"""L0 smoke: HierarchicalMemory 在 import time 满足 Memory Protocol.

老 supervisor 图退役(Phase 7):chat router 的 _build_graph_singleton 随老图删除,
原 test_chat_router_imports_hierarchical_memory(断言 singleton 实例化 HierarchicalMemory)
一并移除 —— chat 现在由 chatloop worker 构 memory,不再在 router 层建图。
"""

from __future__ import annotations


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
