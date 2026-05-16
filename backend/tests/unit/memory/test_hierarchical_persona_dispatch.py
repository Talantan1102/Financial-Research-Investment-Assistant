"""Plan Task 17 — HierarchicalMemory core_memory_* persona block 转译."""

from __future__ import annotations

import contextlib
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from app.memory.hierarchical import HierarchicalMemory


def _mk_memory(**overrides: Any) -> HierarchicalMemory:
    defaults = {
        "pg_session_factory": MagicMock(),
        "age_executor": MagicMock(),
        "milvus_client": MagicMock(),
        "embed_service": MagicMock(),
        "llm_extractor": MagicMock(),
        "llm_judge": MagicMock(),
    }
    defaults.update(overrides)
    return HierarchicalMemory(**defaults)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_core_memory_append_persona_routes_to_persona_service() -> None:
    mock_persona_service = MagicMock()
    mock_persona_service.apply_agent_append.return_value = []
    mem = _mk_memory(persona_service=mock_persona_service)

    await mem.core_memory_append(user_id=uuid4(), block_name="persona", content="X")

    mock_persona_service.apply_agent_append.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_core_memory_append_scratchpad_keeps_legacy_path() -> None:
    """scratchpad block 走原 ChatMemoryWorkingBlock 路径，不调 PersonaService."""
    mock_persona_service = MagicMock()
    mem = _mk_memory(persona_service=mock_persona_service)

    # 不验证完整 PG 路径，只验证 PersonaService 没被调
    with contextlib.suppress(Exception):
        await mem.core_memory_append(user_id=uuid4(), block_name="scratchpad", content="X")

    mock_persona_service.apply_agent_append.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_core_memory_replace_persona_routes_to_persona_service() -> None:
    mock_persona_service = MagicMock()
    mock_persona_service.apply_agent_replace.return_value = []
    mem = _mk_memory(persona_service=mock_persona_service)

    await mem.core_memory_replace(
        user_id=uuid4(), block_name="persona", old_content="A", new_content="B"
    )

    mock_persona_service.apply_agent_replace.assert_called_once_with(
        user_id=mock_persona_service.apply_agent_replace.call_args.kwargs["user_id"],
        old_content="A",
        new_content="B",
    )
