"""MCP tool — recall_memory_search (Tier 3 chat history semantic search).

Spec § 6 Tier 3; Plan 4 ship (wraps RecallSearcher in app.memory.recall_search).

Searches PR #39 ship 的 chat_messages 表 via qwen embed (in-memory cosine,
last 5000 messages cap per user).
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from mcp.types import TextContent, Tool
from pydantic import BaseModel, Field

TOOL_DEF = Tool(
    name="recall_memory_search",
    description=(
        "Semantic search over user's past chat messages (Tier 3 recall). Use for "
        "queries like '我们上次聊过 X' / '你之前说过 Y'. Each result includes "
        "source_session_id and message_id for provenance / chain to verbatim "
        "retrieval."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "query": {"type": "string", "minLength": 1},
            "k": {
                "type": "integer",
                "minimum": 1,
                "maximum": 20,
                "default": 5,
            },
        },
        "required": ["user_id", "query"],
    },
)


class RecallMemorySearchArgs(BaseModel):
    user_id: UUID
    query: str = Field(min_length=1)
    k: int = Field(default=5, ge=1, le=20)


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.mcp_server.tools.memory._common import (
        Timer,
        build_memory_from_env,
        write_tool_call_log,
    )

    validated = RecallMemorySearchArgs.model_validate(args)
    memory = build_memory_from_env()

    err: str | None = None
    results: list[dict[str, Any]] = []
    timer = Timer()
    try:
        with timer:
            results = await memory.recall_memory_search(
                user_id=validated.user_id,
                query=validated.query,
                k=validated.k,
            )
    except Exception as exc:
        err = repr(exc)
        raise
    finally:
        write_tool_call_log(
            user_id=validated.user_id,
            tool_name="recall_memory_search",
            args_json={"query": validated.query[:120], "k": validated.k},
            result_count=len(results),
            latency_ms=timer.elapsed_ms,
            error=err,
        )

    return [
        TextContent(
            type="text",
            text=json.dumps(
                {"results": results, "count": len(results)},
                ensure_ascii=False,
            ),
        )
    ]
