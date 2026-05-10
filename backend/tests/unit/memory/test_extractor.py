"""L0 unit tests for LLMExtractor — schema validation + extraction prompt."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.memory.extractor import (
    ExtractedEdge,
    ExtractedEntity,
    ExtractionOutput,
    LLMExtractor,
)


def test_extracted_edge_importance_three_tier_only() -> None:
    """Importance 必须三档之一: 0.9 / 0.5 / 0.2."""
    ExtractedEdge(
        rel_type="HOLDS",
        source_label="User",
        target_label="600519.SH",
        valid_from="2026-05-10T00:00:00+08:00",
        valid_to=None,
        importance=0.9,
        reasoning="持仓",
        properties={},
    )
    with pytest.raises(ValueError, match="importance"):
        ExtractedEdge(
            rel_type="HOLDS",
            source_label="User",
            target_label="600519.SH",
            valid_from="2026-05-10T00:00:00+08:00",
            valid_to=None,
            importance=0.7,  # 非三档值, 必须 reject
            reasoning="x",
            properties={},
        )


def test_extracted_edge_rel_type_must_be_in_whitelist() -> None:
    """rel_type 必须在 11 类 REL_TYPES 白名单内."""
    with pytest.raises(ValueError, match="rel_type"):
        ExtractedEdge(
            rel_type="LOVES",  # 不在白名单
            source_label="User",
            target_label="600519.SH",
            valid_from="2026-05-10T00:00:00+08:00",
            valid_to=None,
            importance=0.5,
            reasoning="x",
            properties={},
        )


def test_extracted_entity_type_must_be_in_whitelist() -> None:
    """entity_type 必须在 7 类 ENTITY_TYPES 白名单内."""
    ExtractedEntity(entity_type="Stock", entity_label="600519.SH", properties={})
    with pytest.raises(ValueError, match="entity_type"):
        ExtractedEntity(entity_type="Bond", entity_label="x", properties={})


@pytest.mark.asyncio
async def test_extractor_parses_valid_json_response() -> None:
    """LLM 返回 valid JSON → 解析成 ExtractionOutput."""
    fake_llm = AsyncMock()
    fake_llm.chat.return_value = json.dumps(
        {
            "entities": [
                {"entity_type": "User", "entity_label": "User", "properties": {}},
                {"entity_type": "Stock", "entity_label": "600519.SH", "properties": {}},
            ],
            "edges": [
                {
                    "rel_type": "HOLDS",
                    "source_label": "User",
                    "target_label": "600519.SH",
                    "valid_from": "2026-05-10T00:00:00+08:00",
                    "valid_to": None,
                    "importance": 0.9,
                    "reasoning": "用户说持有",
                    "properties": {"qty": 500},
                }
            ],
        }
    )

    extractor = LLMExtractor(llm_client=fake_llm)
    output = await extractor.extract(
        user_message="我持有 500 股茅台",
        agent_response="好的, 已记录.",
        episode_id=uuid4(),
    )
    assert isinstance(output, ExtractionOutput)
    assert len(output.entities) == 2
    assert len(output.edges) == 1
    assert output.edges[0].rel_type == "HOLDS"
    assert output.edges[0].importance == 0.9


@pytest.mark.asyncio
async def test_extractor_invalid_json_raises_value_error() -> None:
    """LLM 返回非 JSON → ValueError, 上层 fail-safe."""
    fake_llm = AsyncMock()
    fake_llm.chat.return_value = "I'm sorry, I can't extract."

    extractor = LLMExtractor(llm_client=fake_llm)
    with pytest.raises(ValueError, match="invalid JSON"):
        await extractor.extract(user_message="hi", agent_response="hi", episode_id=uuid4())


@pytest.mark.asyncio
async def test_extractor_empty_extraction_returns_empty_output() -> None:
    """LLM 觉得没东西可抽 → 返回 entities=[], edges=[]."""
    fake_llm = AsyncMock()
    fake_llm.chat.return_value = json.dumps({"entities": [], "edges": []})

    extractor = LLMExtractor(llm_client=fake_llm)
    output = await extractor.extract(
        user_message="今天天气真好",
        agent_response="是的!",
        episode_id=uuid4(),
    )
    assert output.entities == []
    assert output.edges == []
