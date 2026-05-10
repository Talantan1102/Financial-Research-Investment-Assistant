"""L0 — ChatState 新增 routing 4 字段 schema 验证(Plan 6)。

字段:
    retrieval_targets: list[str] = []
    memory_hits: list[dict] = []
    kb_hits: list[dict] = []
    memory_kb_routing_reasoning: str | None = None

backward compat: 4 字段都默认空,旧调用方零迁移。
"""

from __future__ import annotations

from typing import Any

import pytest
from app.agents.schemas import ChatState


def _base_state(**overrides: Any) -> ChatState:
    base: dict[str, Any] = {
        "user_id": "u1",
        "session_id": "s1",
        "user_message": "hi",
        "request_id": "r1",
        "trace_request_id": "r1",
    }
    base.update(overrides)
    return ChatState(**base)


class TestChatStateRoutingFields:
    def test_default_empty(self) -> None:
        s = _base_state()
        assert s.retrieval_targets == []
        assert s.memory_hits == []
        assert s.kb_hits == []
        assert s.memory_kb_routing_reasoning is None

    def test_set_retrieval_targets(self) -> None:
        s = _base_state(retrieval_targets=["both"])
        assert s.retrieval_targets == ["both"]

    def test_invalid_retrieval_target_rejected(self) -> None:
        with pytest.raises(ValueError):
            _base_state(retrieval_targets=["bogus"])

    def test_memory_hits_arbitrary_dicts(self) -> None:
        s = _base_state(
            memory_hits=[{"edge_id": "e1", "content": {"foo": "bar"}, "rrf_score": 0.42}]
        )
        assert len(s.memory_hits) == 1

    def test_kb_hits_kb_hit_dict_form(self) -> None:
        # 跟 KbSearchService.search 返回的 KbHit 序列化兼容
        s = _base_state(
            kb_hits=[
                {
                    "chunk_id": "c1",
                    "chunk_text": "茅台 2024 Q3 净利润 ...",
                    "similarity": 0.82,
                    "metadata": {"broker": "中金"},
                }
            ]
        )
        assert s.kb_hits[0]["chunk_id"] == "c1"

    def test_routing_reasoning_str(self) -> None:
        s = _base_state(memory_kb_routing_reasoning="memory word hit: '我'")
        assert s.memory_kb_routing_reasoning == "memory word hit: '我'"

    def test_backward_compat_existing_chat_state_callers(self) -> None:
        # 旧调用方不传 4 新字段也能 instantiate
        s = ChatState(
            user_id="u1",
            session_id="s1",
            user_message="x",
            request_id="r1",
            trace_request_id="r1",
        )
        assert s.retrieval_targets == []
        assert s.memory_hits == []
        assert s.kb_hits == []
        assert s.memory_kb_routing_reasoning is None
