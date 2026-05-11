"""MCP tool — core_memory_append (Tier 1 working memory write).

Spec § 6 Tier 1; Plan 4 ship.

Wraps HierarchicalMemory.core_memory_append. Per spec, max 200 chars per call;
auto-paging if append exceeds block max_tokens (oldest line archived).
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from mcp.types import TextContent, Tool
from pydantic import BaseModel, Field, field_validator

TOOL_DEF = Tool(
    name="core_memory_append",
    description=(
        "Append durable fact to user's working memory block. Block names: 'persona' "
        "(long-term identity) or 'scratchpad' (recent context). Auto-paging if exceed "
        "max_tokens (oldest line archived). Max 200 chars per call."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string", "description": "UUID"},
            "block_name": {
                "type": "string",
                "enum": ["persona", "scratchpad"],
            },
            "content": {"type": "string", "maxLength": 200},
        },
        "required": ["user_id", "block_name", "content"],
    },
)


class CoreMemoryAppendArgs(BaseModel):
    user_id: UUID
    block_name: str = Field(pattern="^(persona|scratchpad)$")
    content: str = Field(max_length=200, min_length=1)

    @field_validator("content")
    @classmethod
    def non_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("content must not be empty / whitespace-only")
        return v


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.mcp_server.tools.memory._common import (
        Timer,
        build_memory_from_env,
        write_tool_call_log,
    )
    from app.memory.injection_classifier import (
        PromptInjectionDetectedError,
        is_prompt_injection,
    )

    validated = CoreMemoryAppendArgs.model_validate(args)
    memory = build_memory_from_env()

    err: str | None = None
    block: Any = None
    timer = Timer()
    try:
        with timer:
            # S1 fix — content 写入 working_blocks 前过 injection 分类器
            # ({{persona_block}} / {{scratchpad_block}} 未来回灌 system prompt 风险)
            is_inj, conf, pattern_id = is_prompt_injection(validated.content)
            if is_inj:
                raise PromptInjectionDetectedError(
                    f"core_memory_append content flagged as prompt injection "
                    f"(pattern={pattern_id}, confidence={conf:.2f}) — "
                    f"refusing working_blocks write (algorithm depth patch #2 part a)"
                )
            block = await memory.core_memory_append(
                user_id=validated.user_id,
                block_name=validated.block_name,
                content=validated.content,
            )
    except Exception as exc:
        err = repr(exc)
        raise
    finally:
        write_tool_call_log(
            user_id=validated.user_id,
            tool_name="core_memory_append",
            args_json={
                "block_name": validated.block_name,
                "content_len": len(validated.content),
            },
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
                    "max_tokens": int(block.max_tokens),
                    "within_budget": int(block.token_count) <= int(block.max_tokens),
                },
                ensure_ascii=False,
            ),
        )
    ]
