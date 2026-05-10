"""L0 — memory_kb_router_node 单测(mock memory + mock kb + mock router)。

覆盖:
- memory only → 跳 KB 检索
- kb only → 跳 memory 检索
- both → asyncio.gather 并行
- 单路 fail graceful degrade(both 模式下)
- routing reasoning 持久化到 ChatState 字段
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.agents.schemas import ChatState
from app.memory.memory_kb_router import RouterDecision
from app.orchestration.memory_kb_router_node import memory_kb_router_node


def _state(msg: str = "hi") -> ChatState:
    return ChatState(
        user_id=str(uuid4()),
        session_id=str(uuid4()),
        user_message=msg,
        request_id="rid",
        trace_request_id="rid",
    )


def _fake_edge(edge_id: str = "e1") -> SimpleNamespace:
    return SimpleNamespace(
        edge_id=edge_id,
        rel_type="HOLDS",
        properties={"ts_code": "600519.SH"},
        source_node_id="n1",
        target_node_id="n2",
        importance=0.9,
        valid_from="2024-08-01",
        reasoning="user mentioned",
    )


def _fake_kb_hit() -> SimpleNamespace:
    return SimpleNamespace(
        chunk_id="c1",
        chunk_text="some text",
        similarity=0.8,
        metadata={"broker": "中金"},
    )


class _StubMemory:
    def __init__(self, hits=None, raise_exc=None):
        self.hits = hits or []
        self.raise_exc = raise_exc
        self.calls = 0

    async def archival_memory_search(self, *, user_id, query, k=5):
        self.calls += 1
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.hits


class _StubKb:
    def __init__(self, hits=None, raise_exc=None):
        self.hits = hits or []
        self.raise_exc = raise_exc
        self.calls = 0

    async def search(self, query=None, top_k=5, **kwargs):
        self.calls += 1
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.hits


def _router_returning(decision: RouterDecision):
    async def _fn(query: str) -> RouterDecision:
        return decision

    return _fn


class TestMemoryKbRouterNode:
    async def test_memory_only_skips_kb(self) -> None:
        memory = _StubMemory(hits=[_fake_edge("e1")])
        kb = _StubKb()
        router_fn = _router_returning(
            RouterDecision(retrieval_targets=["memory"], reasoning="mem hit")
        )

        update = await memory_kb_router_node(
            _state("我之前买了什么"),
            memory=memory,  # type: ignore[arg-type]
            kb=kb,  # type: ignore[arg-type]
            router_fn=router_fn,
        )

        assert update["retrieval_targets"] == ["memory"]
        assert update["memory_hits"]
        assert update["kb_hits"] == []
        assert kb.calls == 0  # KB not called

    async def test_kb_only_skips_memory(self) -> None:
        memory = _StubMemory()
        kb = _StubKb(hits=[_fake_kb_hit()])
        router_fn = _router_returning(RouterDecision(retrieval_targets=["kb"], reasoning="kb hit"))

        update = await memory_kb_router_node(
            _state("茅台最新研报"),
            memory=memory,  # type: ignore[arg-type]
            kb=kb,  # type: ignore[arg-type]
            router_fn=router_fn,
        )

        assert update["retrieval_targets"] == ["kb"]
        assert update["kb_hits"]
        assert update["memory_hits"] == []
        assert memory.calls == 0  # memory not called

    async def test_both_runs_in_parallel(self) -> None:
        memory = _StubMemory(hits=[_fake_edge("e1")])
        kb = _StubKb(hits=[_fake_kb_hit()])
        router_fn = _router_returning(RouterDecision(retrieval_targets=["both"], reasoning="both"))

        update = await memory_kb_router_node(
            _state("基于我的持仓推荐"),
            memory=memory,  # type: ignore[arg-type]
            kb=kb,  # type: ignore[arg-type]
            router_fn=router_fn,
        )

        assert update["retrieval_targets"] == ["both"]
        assert update["memory_hits"]
        assert update["kb_hits"]
        assert memory.calls == 1
        assert kb.calls == 1

    async def test_memory_failure_does_not_kill_kb(self) -> None:
        # 鲁棒性 — memory subquery fail 不 kill KB(both 模式下)
        memory = _StubMemory(raise_exc=RuntimeError("PG down"))
        kb = _StubKb(hits=[_fake_kb_hit()])
        router_fn = _router_returning(RouterDecision(retrieval_targets=["both"], reasoning="both"))

        update = await memory_kb_router_node(
            _state("基于我的持仓推荐"),
            memory=memory,  # type: ignore[arg-type]
            kb=kb,  # type: ignore[arg-type]
            router_fn=router_fn,
        )

        assert update["retrieval_targets"] == ["both"]
        assert update["memory_hits"] == []  # graceful degrade
        assert update["kb_hits"]  # still got KB results

    async def test_kb_failure_does_not_kill_memory(self) -> None:
        memory = _StubMemory(hits=[_fake_edge("e1")])
        kb = _StubKb(raise_exc=RuntimeError("milvus down"))
        router_fn = _router_returning(RouterDecision(retrieval_targets=["both"], reasoning="both"))

        update = await memory_kb_router_node(
            _state("基于我的持仓推荐"),
            memory=memory,  # type: ignore[arg-type]
            kb=kb,  # type: ignore[arg-type]
            router_fn=router_fn,
        )

        assert update["retrieval_targets"] == ["both"]
        assert update["memory_hits"]
        assert update["kb_hits"] == []  # graceful degrade

    async def test_reasoning_persisted(self) -> None:
        memory = _StubMemory()
        kb = _StubKb()
        router_fn = _router_returning(
            RouterDecision(retrieval_targets=["memory"], reasoning="memory word hit: '我'")
        )

        update = await memory_kb_router_node(
            _state("我"),
            memory=memory,  # type: ignore[arg-type]
            kb=kb,  # type: ignore[arg-type]
            router_fn=router_fn,
        )
        assert update["memory_kb_routing_reasoning"] == "memory word hit: '我'"

    async def test_anonymous_user_id_does_not_crash(self) -> None:
        # 旧 caller 用 user_id="anonymous" 字面量, 应该 graceful 处理(不抛 ValueError)
        memory = _StubMemory()
        kb = _StubKb()
        router_fn = _router_returning(RouterDecision(retrieval_targets=["memory"], reasoning="x"))

        s = ChatState(
            user_id="anonymous",
            session_id="s",
            user_message="m",
            request_id="r",
            trace_request_id="r",
        )
        update = await memory_kb_router_node(
            s,
            memory=memory,  # type: ignore[arg-type]
            kb=kb,  # type: ignore[arg-type]
            router_fn=router_fn,
        )
        assert update["retrieval_targets"] == ["memory"]


# 防止 pytest-asyncio strict mode 报 missing marker
pytestmark = pytest.mark.asyncio
