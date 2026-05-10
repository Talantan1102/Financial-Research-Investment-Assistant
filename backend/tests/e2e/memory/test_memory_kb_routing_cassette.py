"""L2 cassette — both 类 query 真 LLM 响应不矛盾化(spec § 11 末尾 #7 量化验证)。

Scenario(用户偏好白马 vs 市场跑输 — 经典 trade-off):
- memory_hits: PREFERS 白马 + valid_from=2024-09-01
- kb_hits: 研报片段说"白马股近 6 月跑输大盘 5%"
- 期望: LLM responder 输出语义保持 trade-off 框架,不会将其结论化为"用户偏好错了" /
        "信号矛盾建议立即换"等。

录制方式(作者侧 dogfood):
    DASHSCOPE_API_KEY=... uv run pytest \
        backend/tests/e2e/memory/test_memory_kb_routing_cassette.py \
        --record-mode=once

回放方式(CI):
    uv run pytest backend/tests/e2e/memory/test_memory_kb_routing_cassette.py
    # cassette 已 ship,回放本地无 LLM cost

无 cassette + 无 API key 时 skip,保 fresh checkout / CI 绿。
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from app.agents.chat_planner import ChatPlanner
from app.agents.responder import Responder
from app.agents.schemas import ChatState
from app.memory.memory_kb_router import RouterDecision
from app.orchestration.chat_graph import build_chat_graph
from app.services.kb_search_service import KbHit
from app.services.tool_result_cache import ToolResultCache
from app.tools.registry import ToolRegistry

pytestmark = pytest.mark.e2e

CASSETTE_DIR = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "cassettes"
    / "test_memory_kb_routing_cassette"
)


def _fake_edge() -> SimpleNamespace:
    return SimpleNamespace(
        edge_id="e1",
        rel_type="PREFERS",
        properties={"label": "白马股", "strategy": "long-term"},
        source_node_id="n1",
        target_node_id="n2",
        importance=0.9,
        valid_from="2024-09-01",
        reasoning="user explicitly prefers white-horse blue-chips for stability",
    )


class _StubMemory:
    def __init__(self, hits: list[Any] | None = None) -> None:
        self._hits = hits or []

    def dedup_tool_results(self, results: list[Any]) -> list[Any]:
        return results

    def needs_summarize(self, state: ChatState, max_tokens: int = 0) -> bool:
        return False

    async def summarize(self, state: ChatState) -> str:
        return ""

    async def load_for_turn(self, *args: Any, **kwargs: Any) -> Any:
        return None

    async def save_after_turn(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def archival_memory_search(self, *, user_id: Any, query: str, k: int = 5) -> list[Any]:
        return self._hits


class _StubKb:
    def __init__(self, hits: list[KbHit] | None = None) -> None:
        self._hits = hits or []

    async def search(
        self,
        query: str | None = None,
        collections: list[str] | None = None,
        top_k: int = 5,
        threshold: float | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[KbHit]:
        return self._hits


@pytest.mark.vcr
async def test_both_query_no_contradiction_framing(
    request: pytest.FixtureRequest,
) -> None:
    """跨 memory(用户偏好白马)+ kb(白马跑输)的典型 both — LLM 应保 trade-off frame.

    跑该 test 需要 cassette;若不存在且无 DASHSCOPE_API_KEY 则 skip。
    """
    cassette_path = CASSETTE_DIR / (f"{request.node.originalname or request.node.name}.yaml")
    record_mode = os.environ.get("VCR_RECORD_MODE", "none")
    if record_mode == "none" and not cassette_path.exists():
        pytest.skip(
            "cassette not recorded yet; record with "
            "VCR_RECORD_MODE=once + DASHSCOPE_API_KEY before running offline. "
            "Plan 6 ship 暂不带 cassette 文件 — 作者本地 dogfood 时录制。"
        )

    # === 1. mock memory + kb,只 LLM 真调 ===
    memory = _StubMemory(hits=[_fake_edge()])
    kb = _StubKb(
        hits=[
            KbHit(
                chunk_id="c1",
                chunk_text=(
                    "近 6 月白马股跑输大盘约 5%, 资金加速流向中小盘成长股。"
                    "但中长期看, 白马股的 ROE 稳定性仍优于成长板块。"
                ),
                similarity=0.85,
                metadata={
                    "broker": "中金",
                    "pub_date": "2024-10-30",
                    "industry": "策略",
                },
            )
        ]
    )

    async def router_fn(query: str) -> RouterDecision:
        return RouterDecision(
            retrieval_targets=["both"],
            reasoning="user mentions 我的偏好 + asks for current market view",
        )

    # === 2. 真 LLM via cassette ===
    from app.services.openai_client import build_llm_service_from_env

    llm = build_llm_service_from_env()  # qwen-plus

    registry = ToolRegistry()
    cache = ToolResultCache(session_factory=MagicMock())
    planner = ChatPlanner(llm=llm, registry=registry, available_tools=[])
    responder = Responder(llm=llm)

    graph = build_chat_graph(
        planner=planner,
        responder=responder,
        registry=registry,
        memory=memory,
        cache=cache,
        kb_search_service=kb,
        memory_kb_router_fn=router_fn,
    )

    initial = ChatState(
        user_id=str(uuid4()),
        session_id=str(uuid4()),
        user_message="基于我的偏好分析下当前市场,给我一些建议",
        request_id="rid",
        trace_request_id="rid",
    )
    final = await graph.ainvoke(initial.model_dump())

    response = final.get("final_response") or ""

    # === 3. 不矛盾化断言 ===
    contradiction_words = ["矛盾", "冲突", "对立", "完全错误", "立刻换仓", "马上抛"]
    tradeoff_words = [
        "权衡",
        "平衡",
        "取舍",
        "trade-off",
        "trade off",
        "短期",
        "长期",
        "考虑",
    ]

    for w in contradiction_words:
        assert w not in response, (
            f"LLM 输出意外含矛盾化词 {w!r} — 用户偏好 vs 市场跑输应该是 trade-off。\n"
            f"完整响应: {response[:500]}"
        )

    assert any(w in response for w in tradeoff_words), (
        f"LLM 未保留 trade-off 框架 — 期望含 {tradeoff_words} 至少一个。\n"
        f"完整响应: {response[:500]}"
    )

    # === 4. routing 状态正确 ===
    assert final["retrieval_targets"] == ["both"]
    assert final["memory_hits"]
    assert final["kb_hits"]
