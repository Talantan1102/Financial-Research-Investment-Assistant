"""L0 — ChatPlanner planner prompt 区隔段(spec § 11 末尾 #7 (c))。

两路结果 prompt 显式区隔:
- `[用户上下文]` — 来自用户私人记忆(memory_hits)
- `[市场知识]` — 来自公开知识库(kb_hits)
- both 时加 disclaimer 让 LLM 不混淆个人事实 vs 公开知识
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from app.agents.chat_planner import ChatPlanner
from app.agents.schemas import ChatState
from app.services.llm_service import LLMService


def _make_planner() -> ChatPlanner:
    mock_llm = MagicMock(spec=LLMService)
    return ChatPlanner(llm=mock_llm, available_tools=["get_stock_quote"])


def _state(memory_hits: list[dict[str, Any]], kb_hits: list[dict[str, Any]]) -> ChatState:
    targets: list[str] = []
    if memory_hits and kb_hits:
        targets = ["both"]
    elif memory_hits:
        targets = ["memory"]
    elif kb_hits:
        targets = ["kb"]
    return ChatState(
        user_id="u1",
        session_id="s1",
        user_message="基于我的持仓推荐",
        request_id="r1",
        trace_request_id="r1",
        memory_hits=memory_hits,
        kb_hits=kb_hits,
        retrieval_targets=targets,
    )


class TestPlannerPromptSegregation:
    @pytest.mark.asyncio
    async def test_no_routing_results_no_segregation_blocks(self) -> None:
        # 没有 routing 结果 — prompt 不应注入 [用户上下文] / [市场知识] 段
        planner = _make_planner()
        prompt = await planner._build_chat_prompt(_state(memory_hits=[], kb_hits=[]))
        assert "[用户上下文]" not in prompt
        assert "[市场知识]" not in prompt

    @pytest.mark.asyncio
    async def test_memory_only_injects_user_context_block(self) -> None:
        planner = _make_planner()
        prompt = await planner._build_chat_prompt(
            _state(
                memory_hits=[
                    {
                        "rel_type": "HOLDS",
                        "properties": {"ts_code": "600519.SH"},
                        "valid_from": "2024-08-01",
                    }
                ],
                kb_hits=[],
            )
        )
        assert "[用户上下文]" in prompt
        assert "HOLDS" in prompt
        assert "600519.SH" in prompt
        assert "[市场知识]" not in prompt

    @pytest.mark.asyncio
    async def test_kb_only_injects_market_knowledge_block(self) -> None:
        planner = _make_planner()
        prompt = await planner._build_chat_prompt(
            _state(
                memory_hits=[],
                kb_hits=[
                    {
                        "chunk_id": "c1",
                        "chunk_text": "茅台 Q3 净利润同比+15%",
                        "similarity": 0.82,
                        "metadata": {"broker": "中金"},
                    }
                ],
            )
        )
        assert "[市场知识]" in prompt
        assert "茅台 Q3" in prompt
        assert "[用户上下文]" not in prompt

    @pytest.mark.asyncio
    async def test_both_injects_both_blocks_separately(self) -> None:
        planner = _make_planner()
        prompt = await planner._build_chat_prompt(
            _state(
                memory_hits=[
                    {
                        "rel_type": "PREFERS",
                        "properties": {"label": "白马股"},
                        "valid_from": "2024-09-01",
                    }
                ],
                kb_hits=[
                    {
                        "chunk_id": "c1",
                        "chunk_text": "白马股近 6 月跑输大盘",
                        "similarity": 0.9,
                        "metadata": {},
                    }
                ],
            )
        )
        # 两段都在,且 [用户上下文] 在 [市场知识] 之前 — 让 LLM 先把私人信息当 frame
        idx_user = prompt.find("[用户上下文]")
        idx_mkt = prompt.find("[市场知识]")
        assert 0 <= idx_user < idx_mkt

    @pytest.mark.asyncio
    async def test_segregation_prompt_explicit_disclaimer(self) -> None:
        # spec § 11 末尾 #7 (c): 让 LLM 不混淆个人事实和公开知识
        planner = _make_planner()
        prompt = await planner._build_chat_prompt(
            _state(
                memory_hits=[{"rel_type": "PREFERS", "properties": {}, "valid_from": "2024"}],
                kb_hits=[
                    {
                        "chunk_id": "c1",
                        "chunk_text": "x",
                        "similarity": 0.5,
                        "metadata": {},
                    }
                ],
            )
        )
        # 必须含明确告知 LLM 两段含义不同的 disclaimer
        assert "个人事实" in prompt or "不要把" in prompt or "区分" in prompt
        # 经典示例: 用户偏好白马 + 市场跑输 = trade-off 不是矛盾
        assert "trade-off" in prompt or "矛盾" in prompt

    @pytest.mark.asyncio
    async def test_top5_truncation(self) -> None:
        # 防爆 — memory_hits 超过 5 时只渲染 top-5
        planner = _make_planner()
        many_hits = [
            {
                "rel_type": f"REL_{i}",
                "properties": {"ts_code": f"600{i:03d}.SH"},
                "valid_from": "2024-08-01",
            }
            for i in range(10)
        ]
        prompt = await planner._build_chat_prompt(_state(memory_hits=many_hits, kb_hits=[]))
        # 前 5 应该在,后面 5 不应该在
        assert "REL_0" in prompt
        assert "REL_4" in prompt
        assert "REL_9" not in prompt

    @pytest.mark.asyncio
    async def test_kb_chunk_text_truncated(self) -> None:
        planner = _make_planner()
        long_text = "A" * 500
        prompt = await planner._build_chat_prompt(
            _state(
                memory_hits=[],
                kb_hits=[
                    {
                        "chunk_id": "c1",
                        "chunk_text": long_text,
                        "similarity": 0.7,
                        "metadata": {},
                    }
                ],
            )
        )
        # 240 char 截断
        # 计数: 找连续的 'A',应当 <= 250 (允许少量 metadata 字符)
        assert "A" * 500 not in prompt
