"""MCP tool — archival_memory_insert (Tier 2 graph write).

Spec § 6 Tier 2 + § 11 末尾 #2 (algorithm 深度补丁 #2 part b: evidence_quote
substring 校验). Plan 4 ship.

Pipeline:
  1. Pydantic validate (incl. importance ∈ {0.9, 0.5, 0.2}).
  2. Fetch episode by (episode_id, user_id) — ownership check.
  3. evidence_quote_in_episode substring check on
     user_message_text + agent_response_text. Fail → EvidenceNotFoundError.
  4. Enrich content with source_entity_type / target_entity_type / valid_from
     defaults (HierarchicalMemory needs these but the MCP tool surface is
     shorthand per spec § 6).
  5. Call HierarchicalMemory.archival_memory_insert (Plan 2A 8-step pipeline).
  6. Always log to mcp_tool_call_log (success or failure).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from mcp.types import TextContent, Tool
from pydantic import BaseModel, Field, field_validator

TOOL_DEF = Tool(
    name="archival_memory_insert",
    description=(
        "Write fact to graph memory (Tier 2 archival). Runs full 8-step write "
        "pipeline including entity normalize / 4-action conflict resolution / "
        "AGE+Milvus sync. evidence_quote MUST be a substring of source episode "
        "text (algorithm depth patch #2 — prevents agent hallucination). "
        "importance: 0.9=explicit identity, 0.5=contextual, 0.2=weak signal "
        "(three-tier discrete)."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "content": {
                "type": "object",
                "properties": {
                    "rel_type": {"type": "string"},
                    "source_label": {"type": "string"},
                    "target_label": {"type": "string"},
                    "source_entity_type": {
                        "type": "string",
                        "description": "Optional override (User/Stock/Industry/...)",
                    },
                    "target_entity_type": {
                        "type": "string",
                        "description": "Optional override (User/Stock/Industry/...)",
                    },
                    "valid_from": {
                        "type": "string",
                        "description": "ISO datetime, optional (default now)",
                    },
                    "properties": {"type": "object"},
                },
                "required": ["rel_type", "source_label", "target_label"],
            },
            "reasoning": {
                "type": "string",
                "description": "agent's reason for this insertion",
            },
            "importance": {"type": "number", "enum": [0.9, 0.5, 0.2]},
            "evidence_quote": {
                "type": "string",
                "description": "verbatim substring from episode text supporting this fact",
                "minLength": 1,
            },
            "episode_id": {
                "type": "string",
                "description": "UUID of source episode",
            },
        },
        "required": [
            "user_id",
            "content",
            "reasoning",
            "importance",
            "evidence_quote",
            "episode_id",
        ],
    },
)


class ArchivalMemoryInsertArgs(BaseModel):
    user_id: UUID
    content: dict[str, Any]
    reasoning: str = Field(min_length=1)
    # 三档约束 spec § 11 末尾 #3 — Pydantic Literal rejects 0.7 etc.
    importance: Literal[0.9, 0.5, 0.2]
    evidence_quote: str = Field(min_length=1)
    episode_id: UUID

    @field_validator("content")
    @classmethod
    def content_has_required(cls, v: dict[str, Any]) -> dict[str, Any]:
        for key in ("rel_type", "source_label", "target_label"):
            if key not in v:
                raise ValueError(f"content missing required key: {key}")
        return v

    @field_validator("evidence_quote")
    @classmethod
    def evidence_non_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("evidence_quote must not be whitespace-only")
        return v


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from sqlalchemy import select

    from app.mcp_server.tools.memory._common import (
        Timer,
        build_db_session,
        get_memory,  # C50: use singleton to avoid per-call connection leak
        infer_entity_types,
        write_tool_call_log,
    )
    from app.memory.injection_classifier import (
        EvidenceNotFoundError,
        PromptInjectionDetectedError,
        evidence_quote_in_episode,
        is_prompt_injection,
    )
    from app.memory.models import ChatMemoryEpisode

    validated = ArchivalMemoryInsertArgs.model_validate(args)

    err: str | None = None
    edge: Any = None
    timer = Timer()
    try:
        with timer:
            # ---- 1) Ownership + evidence_quote substring 校验 ----
            db = build_db_session()
            try:
                row = db.execute(
                    select(ChatMemoryEpisode).where(
                        ChatMemoryEpisode.episode_id == validated.episode_id,
                        ChatMemoryEpisode.user_id == validated.user_id,
                    )
                )
                episode = row.scalar_one_or_none()
                if episode is None:
                    raise ValueError(
                        f"episode {validated.episode_id} not found "
                        f"or not owned by user {validated.user_id}"
                    )

                episode_text = (
                    (episode.user_message_text or "") + "\n" + (episode.agent_response_text or "")
                )
                # S1 fix — prompt injection 拦截 (spec § 11 末尾 #2 part a; 死代码修复)
                is_inj, conf, pattern_id = is_prompt_injection(episode_text)
                if is_inj:
                    raise PromptInjectionDetectedError(
                        f"episode {validated.episode_id} flagged as prompt injection "
                        f"(pattern={pattern_id}, confidence={conf:.2f}) — "
                        f"refusing graph write (algorithm depth patch #2 part a)"
                    )
                # C51: also screen agent-supplied evidence_quote and reasoning —
                # contract in injection_classifier.PromptInjectionDetectedError
                # docstring lists all three fields; previously only episode_text
                # was checked, leaving a gap if reasoning/evidence_quote are ever
                # rendered back into a system prompt.
                is_inj, conf, pattern_id = is_prompt_injection(validated.evidence_quote)
                if is_inj:
                    raise PromptInjectionDetectedError(
                        f"evidence_quote flagged as prompt injection "
                        f"(pattern={pattern_id}, confidence={conf:.2f}) — "
                        f"refusing graph write (algorithm depth patch #2 part a)"
                    )
                is_inj, conf, pattern_id = is_prompt_injection(validated.reasoning)
                if is_inj:
                    raise PromptInjectionDetectedError(
                        f"reasoning flagged as prompt injection "
                        f"(pattern={pattern_id}, confidence={conf:.2f}) — "
                        f"refusing graph write (algorithm depth patch #2 part a)"
                    )
                if not evidence_quote_in_episode(validated.evidence_quote, episode_text):
                    raise EvidenceNotFoundError(
                        f"evidence_quote {validated.evidence_quote!r} not a "
                        f"substring of episode {validated.episode_id} — "
                        f"refusing write to prevent agent hallucination "
                        f"(algorithm depth patch #2)"
                    )
            finally:
                db.close()

            # ---- 2) Enrich content + call Memory Protocol ----
            content = dict(validated.content)
            rel_type = str(content["rel_type"])
            source_label = str(content["source_label"])
            target_label = str(content["target_label"])

            inferred_src, inferred_tgt = infer_entity_types(rel_type, source_label, target_label)
            content.setdefault("source_entity_type", inferred_src)
            content.setdefault("target_entity_type", inferred_tgt)
            # valid_from default = now; allow ISO override
            if "valid_from" in content and isinstance(content["valid_from"], str):
                content["valid_from"] = datetime.fromisoformat(content["valid_from"])
            content.setdefault("valid_from", datetime.now(UTC))

            memory = get_memory()  # C50: singleton, not a fresh instance per call
            edge = await memory.archival_memory_insert(
                user_id=validated.user_id,
                content=content,
                reasoning=validated.reasoning,
                importance=float(validated.importance),
                evidence_quote=validated.evidence_quote,
                episode_id=validated.episode_id,
            )
    except Exception as exc:
        err = repr(exc)
        raise
    finally:
        write_tool_call_log(
            user_id=validated.user_id,
            tool_name="archival_memory_insert",
            args_json={
                "rel_type": validated.content.get("rel_type"),
                "importance": float(validated.importance),
                "episode_id": str(validated.episode_id),
            },
            result_count=1 if edge is not None else 0,
            latency_ms=timer.elapsed_ms,
            error=err,
        )

    if edge is None:
        # NO_OP path (HierarchicalMemory returns None for spec § 4 Step 5 重复事实)
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "edge_id": None,
                        "action": "no_op",
                        "source_episode_id": str(validated.episode_id),
                    },
                    ensure_ascii=False,
                ),
            )
        ]

    return [
        TextContent(
            type="text",
            text=json.dumps(
                {
                    "edge_id": str(edge.edge_id),
                    "source_episode_id": str(edge.source_episode_id),
                    "rel_type": edge.rel_type,
                    "importance": (float(edge.importance) if edge.importance is not None else None),
                    "valid_from": (edge.valid_from.isoformat() if edge.valid_from else None),
                },
                ensure_ascii=False,
            ),
        )
    ]
