"""MCP tool — core_memory_replace (Tier 1 exact-substring replace).

Spec § 6 Tier 1; Plan 4 ship.

Wraps HierarchicalMemory.core_memory_replace. old_content must exact-match an
existing substring; ValueError raised if not found (HierarchicalMemory layer).
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from mcp.types import TextContent, Tool
from pydantic import BaseModel, Field

TOOL_DEF = Tool(
    name="core_memory_replace",
    description=(
        "Replace exact substring in working memory block. Raises ValueError if "
        "old_content not found. Use for updating; pair with core_memory_append for "
        "additions."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "block_name": {"type": "string", "enum": ["persona", "scratchpad"]},
            "old_content": {"type": "string", "minLength": 1},
            "new_content": {"type": "string", "maxLength": 500},
        },
        "required": ["user_id", "block_name", "old_content", "new_content"],
    },
)


class CoreMemoryReplaceArgs(BaseModel):
    user_id: UUID
    block_name: str = Field(pattern="^(persona|scratchpad)$")
    old_content: str = Field(min_length=1)
    new_content: str = Field(max_length=500)


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.mcp_server.tools.memory._common import (
        Timer,
        build_memory_from_env,
        write_tool_call_log,
    )

    validated = CoreMemoryReplaceArgs.model_validate(args)
    memory = build_memory_from_env()

    err: str | None = None
    block: Any = None
    timer = Timer()
    try:
        with timer:
            block = await memory.core_memory_replace(
                user_id=validated.user_id,
                block_name=validated.block_name,
                old_content=validated.old_content,
                new_content=validated.new_content,
            )
    except Exception as exc:
        err = repr(exc)
        raise
    finally:
        write_tool_call_log(
            user_id=validated.user_id,
            tool_name="core_memory_replace",
            args_json={"block_name": validated.block_name},
            result_count=1 if block is not None else 0,
            latency_ms=timer.elapsed_ms,
            error=err,
        )

    return [
        TextContent(
            type="text",
            text=json.dumps(
                {
                    "block_name": validated.block_name,
                    "token_count": int(block.token_count),
                },
                ensure_ascii=False,
            ),
        )
    ]
