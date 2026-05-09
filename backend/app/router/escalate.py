"""POST /api/v0/chat/escalate — confirmed escalation packet handler.

Receives user-confirmed EscalationPacket, persists diff to EscalationRecord,
streams stub `escalate_done` event. Task 9 wires actual ResearchAgent invocation.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agents.escalation_protocol import EscalationPacket, FieldEdit
from app.services.escalation_record_repo import EscalationRecordRepo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v0/chat", tags=["chat-escalate"])


class EscalateRequest(BaseModel):
    draft_record_id: uuid.UUID | str
    packet_confirmed: EscalationPacket
    user_edits: list[FieldEdit] = Field(default_factory=list)


def get_escalation_record_repo() -> EscalationRecordRepo:
    raise RuntimeError("EscalationRecordRepo dependency not configured")


def _format_sse(event: str, data: dict[str, Any], seq: int) -> str:
    body = {**data, "seq": seq}
    return f"event: {event}\ndata: {json.dumps(body, ensure_ascii=False, default=str)}\n\n"


@router.post("/escalate")
async def escalate(
    req: EscalateRequest,
    record_repo: EscalationRecordRepo = Depends(get_escalation_record_repo),
) -> StreamingResponse:
    """Receive confirmed packet, persist diff, stream events (T9 will add ResearchAgent run)."""

    async def _stream() -> AsyncIterator[str]:
        seq = {"n": 0}

        # 1. Persist confirmation (E12 packet diff trace)
        try:
            await record_repo.record_confirmation(
                record_id=req.draft_record_id,
                packet_confirmed=req.packet_confirmed.model_dump(mode="json"),
                user_edits=[e.model_dump(mode="json") for e in req.user_edits],
            )
        except Exception as e:
            logger.exception("escalate: record_confirmation failed")
            seq["n"] += 1
            yield _format_sse("escalate_error", {"error": f"persist failed: {e}"}, seq["n"])
            return

        # 2. Stub: emit escalate_done — T9 replaces with ResearchAgent stream
        seq["n"] += 1
        yield _format_sse(
            "escalate_done",
            {"draft_record_id": str(req.draft_record_id)},
            seq["n"],
        )

    return StreamingResponse(_stream(), media_type="text/event-stream")
