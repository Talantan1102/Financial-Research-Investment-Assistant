"""MCP tool — archival_memory_traverse (Tier 2 explicit graph multi-hop).

Spec § 6 Tier 2 traverse + 附录 D trigger 词清单; Plan 4 ship (wraps Plan 3
graph_traverse).

Trigger words (附录 D / shared contracts § 8 TRAVERSE_TRIGGER_WORDS):
  相关 / 类似 / 同 / 同行业 / 同赛道 / 同概念 / 之间 / 链 / 上下游 / 产业链
  / 属于 / 归类 / 范围 / 覆盖 / 对比 / vs.

Use for topology queries; falls back to archival_memory_search semantically
(MCP tool returns hint=… when result is empty so agent can re-route).
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from mcp.types import TextContent, Tool
from pydantic import BaseModel, Field

TOOL_DEF = Tool(
    name="archival_memory_traverse",
    description=(
        "Explicit graph traversal via AGE Cypher. ONLY use when user query has "
        "topology intent. Trigger words: '相关 / 类似 / 同 / 同行业 / 同赛道 / "
        "同概念 / 之间 / 链 / 上下游 / 产业链 / 属于'. hops default 2 max 3. "
        "rel_types optional filter. Falls back to archival_memory_search on "
        "empty result."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "start_label": {
                "type": "string",
                "description": "Entity label to start traversal from, e.g. '贵州茅台' or 'User'",
                "minLength": 1,
            },
            "hops": {
                "type": "integer",
                "minimum": 1,
                "maximum": 3,
                "default": 2,
            },
            "rel_types": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional rel_type whitelist (e.g. ['BELONGS_TO', 'CORRELATED_WITH'])"
                ),
            },
        },
        "required": ["user_id", "start_label"],
    },
)


class ArchivalMemoryTraverseArgs(BaseModel):
    user_id: UUID
    start_label: str = Field(min_length=1)
    hops: int = Field(default=2, ge=1, le=3)
    rel_types: list[str] | None = None


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.mcp_server.tools.memory._common import (
        Timer,
        build_memory_from_env,
        write_tool_call_log,
    )

    validated = ArchivalMemoryTraverseArgs.model_validate(args)
    memory = build_memory_from_env()

    err: str | None = None
    paths: list[Any] = []
    timer = Timer()
    try:
        with timer:
            paths = await memory.archival_memory_traverse(
                user_id=validated.user_id,
                start_label=validated.start_label,
                hops=validated.hops,
                rel_types=validated.rel_types,
            )
    except Exception as exc:
        err = repr(exc)
        raise
    finally:
        write_tool_call_log(
            user_id=validated.user_id,
            tool_name="archival_memory_traverse",
            args_json={
                "start_label": validated.start_label,
                "hops": validated.hops,
                "rel_types": validated.rel_types,
            },
            result_count=len(paths),
            latency_ms=timer.elapsed_ms,
            error=err,
        )

    return [
        TextContent(
            type="text",
            text=json.dumps(
                {
                    "paths": paths,
                    "count": len(paths),
                    "hint": (
                        "empty result; consider falling back to archival_memory_search"
                        if not paths
                        else None
                    ),
                },
                ensure_ascii=False,
                default=str,  # tolerate datetime / UUID inside path dicts
            ),
        )
    ]
