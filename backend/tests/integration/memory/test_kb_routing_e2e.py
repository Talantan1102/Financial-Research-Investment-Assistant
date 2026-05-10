"""L1 — chat graph 集成 memory_kb_router_node 端到端(mock LLM + mock memory + mock kb)。

Asserts:
- 没注入 kb_search_service → 老 topology 保留(backward compat)
- 注入后 → memory query 走 memory 路径,kb query 走 kb 路径,both query 并行
- raise ValueError 当只注入 kb_search_service 或 memory_kb_router_fn 一个
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from app.agents.chat_planner import ChatPlanner
from app.agents.in_session_memory import InSessionMemory
from app.agents.responder import Responder
from app.agents.schemas import ChatState
from app.memory.memory_kb_router import RouterDecision
from app.orchestration.chat_graph import build_chat_graph
from app.services.kb_search_service import KbHit
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService
from app.services.tool_result_cache import ToolResultCache
from app.tools.registry import ToolRegistry

# Note: asyncio_mode='auto' in pyproject covers async tests automatically; no need
# to set pytestmark = pytest.mark.asyncio here (would warn for sync `def test_*` cases).


def _fake_edge() -> SimpleNamespace:
    return SimpleNamespace(
        edge_id="e1",
        rel_type="HOLDS",
        properties={"ts_code": "600519.SH"},
        source_node_id="n1",
        target_node_id="n2",
        importance=0.9,
        valid_from="2024-08-01",
        reasoning="user mentioned",
    )


class _StubMemory:
    """In-session-memory subset + archival_memory_search stub."""

    def __init__(self, hits: list[Any] | None = None) -> None:
        self._hits = hits or []
        self.search_calls = 0

    def dedup_tool_results(self, results: list[Any]) -> list[Any]:
        return results

    def needs_summarize(self, state: ChatState, max_tokens: int = 0) -> bool:
        return False

    async def summarize(self, state: ChatState) -> str:
        return ""

    async def archival_memory_search(self, *, user_id: Any, query: str, k: int = 5) -> list[Any]:
        self.search_calls += 1
        return self._hits


class _StubKb:
    def __init__(self, hits: list[KbHit] | None = None) -> None:
        self._hits = hits or []
        self.search_calls = 0

    async def search(
        self,
        query: str | None = None,
        collections: list[str] | None = None,
        top_k: int = 5,
        threshold: float | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[KbHit]:
        self.search_calls += 1
        return self._hits


def _make_mock_kb_with_hits() -> _StubKb:
    return _StubKb(
        hits=[
            KbHit(
                chunk_id="c1",
                chunk_text="茅台 2024 Q3 净利润同比增长。",
                similarity=0.82,
                metadata={"broker": "中金", "pub_date": "2024-10-30"},
            )
        ]
    )


def _build_graph(
    mock_llm_client: MockLLMClient,
    *,
    memory: Any,
    kb: Any | None,
    router_fn: Any | None,
):
    svc = LLMService(client=mock_llm_client)
    registry = ToolRegistry()
    cache = ToolResultCache(session_factory=MagicMock())
    planner = ChatPlanner(llm=svc, registry=registry, available_tools=[])
    responder = Responder(llm=svc)
    return build_chat_graph(
        planner=planner,
        responder=responder,
        registry=registry,
        memory=memory,
        cache=cache,
        kb_search_service=kb,
        memory_kb_router_fn=router_fn,
    )


class TestKbRoutingE2E:
    async def test_memory_query_routes_to_memory(self, mock_llm_client: MockLLMClient) -> None:
        memory = _StubMemory(hits=[_fake_edge()])
        kb = _make_mock_kb_with_hits()

        async def router_fn(query: str) -> RouterDecision:
            return RouterDecision(retrieval_targets=["memory"], reasoning="mem")

        graph = _build_graph(mock_llm_client, memory=memory, kb=kb, router_fn=router_fn)

        initial = ChatState(
            user_id=str(uuid4()),
            session_id=str(uuid4()),
            user_message="我之前买了什么",
            request_id="r1",
            trace_request_id="r1",
        )
        final = await graph.ainvoke(initial.model_dump())

        assert final["retrieval_targets"] == ["memory"]
        assert final["memory_hits"]
        assert final["kb_hits"] == []
        assert kb.search_calls == 0
        assert memory.search_calls == 1

    async def test_kb_query_routes_to_kb(self, mock_llm_client: MockLLMClient) -> None:
        memory = _StubMemory(hits=[_fake_edge()])
        kb = _make_mock_kb_with_hits()

        async def router_fn(query: str) -> RouterDecision:
            return RouterDecision(retrieval_targets=["kb"], reasoning="kb")

        graph = _build_graph(mock_llm_client, memory=memory, kb=kb, router_fn=router_fn)

        initial = ChatState(
            user_id=str(uuid4()),
            session_id=str(uuid4()),
            user_message="茅台最新研报",
            request_id="r2",
            trace_request_id="r2",
        )
        final = await graph.ainvoke(initial.model_dump())

        assert final["retrieval_targets"] == ["kb"]
        assert final["kb_hits"]
        assert final["memory_hits"] == []
        assert memory.search_calls == 0
        assert kb.search_calls == 1

    async def test_both_query_runs_parallel(self, mock_llm_client: MockLLMClient) -> None:
        memory = _StubMemory(hits=[_fake_edge()])
        kb = _make_mock_kb_with_hits()

        async def router_fn(query: str) -> RouterDecision:
            return RouterDecision(retrieval_targets=["both"], reasoning="both")

        graph = _build_graph(mock_llm_client, memory=memory, kb=kb, router_fn=router_fn)

        initial = ChatState(
            user_id=str(uuid4()),
            session_id=str(uuid4()),
            user_message="基于我的持仓推荐",
            request_id="r3",
            trace_request_id="r3",
        )
        final = await graph.ainvoke(initial.model_dump())

        assert final["retrieval_targets"] == ["both"]
        assert final["memory_hits"]
        assert final["kb_hits"]
        assert memory.search_calls == 1
        assert kb.search_calls == 1

    async def test_no_kb_service_keeps_legacy_topology(
        self, mock_llm_client: MockLLMClient
    ) -> None:
        # backward compat: 不注入 kb_search_service / memory_kb_router_fn → router node 不挂载
        memory = InSessionMemory()
        graph = _build_graph(mock_llm_client, memory=memory, kb=None, router_fn=None)

        initial = ChatState(
            user_id=str(uuid4()),
            session_id=str(uuid4()),
            user_message="hi",
            request_id="r4",
            trace_request_id="r4",
        )
        final = await graph.ainvoke(initial.model_dump())
        # legacy: retrieval_targets 仍是默认空(router node 没运行)
        assert final["retrieval_targets"] == []
        assert final["memory_hits"] == []
        assert final["kb_hits"] == []

    def test_only_kb_service_without_router_raises(self, mock_llm_client: MockLLMClient) -> None:
        # 只传 kb_search_service 不传 memory_kb_router_fn → ValueError
        memory = InSessionMemory()
        kb = _make_mock_kb_with_hits()
        with pytest.raises(ValueError, match="must be provided together"):
            _build_graph(mock_llm_client, memory=memory, kb=kb, router_fn=None)

    def test_only_router_without_kb_service_raises(self, mock_llm_client: MockLLMClient) -> None:
        memory = InSessionMemory()

        async def router_fn(query: str) -> RouterDecision:
            return RouterDecision(retrieval_targets=["memory"], reasoning="x")

        with pytest.raises(ValueError, match="must be provided together"):
            _build_graph(mock_llm_client, memory=memory, kb=None, router_fn=router_fn)
