"""MCP tool — archival_memory_search (Tier 2 default 3-way hybrid + RRF v2).

Spec § 6 Tier 2 default search; Plan 4 ship (wraps Plan 3 retriever).

DEFAULT memory recall tool — agent uses this for "what did I say about X".
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from mcp.types import TextContent, Tool
from pydantic import BaseModel, Field

TOOL_DEF = Tool(
    name="archival_memory_search",
    description=(
        "DEFAULT memory recall tool — 3-way hybrid (BM25 + dense vector + entity-"
        "anchor expansion) fused with time-aware importance-weighted RRF. Use for "
        "'what did I say about X' queries. k default 5 max 20."
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


class ArchivalMemorySearchArgs(BaseModel):
    user_id: UUID
    query: str = Field(min_length=1)
    k: int = Field(default=5, ge=1, le=20)


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.mcp_server.tools.memory._common import (
        Timer,
        build_memory_from_env,
        write_tool_call_log,
    )

    validated = ArchivalMemorySearchArgs.model_validate(args)
    memory = build_memory_from_env()

    err: str | None = None
    edges: list[Any] = []
    timer = Timer()
    try:
        with timer:
            edges = await memory.archival_memory_search(
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
            tool_name="archival_memory_search",
            args_json={"query": validated.query[:120], "k": validated.k},
            result_count=len(edges),
            latency_ms=timer.elapsed_ms,
            error=err,
        )

    results = [
        {
            "edge_id": str(e.edge_id),
            "rel_type": e.rel_type,
            "source_label": (e.properties.get("source_label") if e.properties else None),
            "target_label": (e.properties.get("target_label") if e.properties else None),
            "valid_from": (e.valid_from.isoformat() if e.valid_from else None),
            "valid_to": (e.valid_to.isoformat() if e.valid_to else None),
            "importance": (float(e.importance) if e.importance is not None else None),
            "reasoning": e.reasoning,
            "source_episode_id": str(e.source_episode_id),
        }
        for e in edges
    ]
    return [
        TextContent(
            type="text",
            text=json.dumps(
                {"results": results, "count": len(results)},
                ensure_ascii=False,
            ),
        )
    ]
