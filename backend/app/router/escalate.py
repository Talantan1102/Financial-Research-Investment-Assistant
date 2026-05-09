"""POST /api/v0/chat/escalate — confirmed escalation packet handler.

Receives user-confirmed EscalationPacket, persists diff to EscalationRecord,
invokes ResearchAgent and streams escalate_done event (E13).
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agents.escalation_protocol import EscalationPacket, FieldEdit
from app.agents.research_agent import ResearchAgent
from app.agents.schemas import ResearchState
from app.services.chat_session_repo import ChatSessionRepo
from app.services.escalation_record_repo import EscalationRecordRepo
from app.services.research_report_repo import ResearchReportRepo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v0/chat", tags=["chat-escalate"])


class EscalateRequest(BaseModel):
    draft_record_id: uuid.UUID | str
    packet_confirmed: EscalationPacket
    user_edits: list[FieldEdit] = Field(default_factory=list)


def get_escalation_record_repo() -> EscalationRecordRepo:
    raise RuntimeError("EscalationRecordRepo dependency not configured")


def get_research_agent() -> ResearchAgent:
    raise RuntimeError("ResearchAgent dependency not configured")


def get_chat_session_repo() -> ChatSessionRepo:
    raise RuntimeError("ChatSessionRepo dependency not configured")


def get_research_report_repo() -> ResearchReportRepo:
    raise RuntimeError("ResearchReportRepo dependency not configured")


def _summarize_report(markdown: str, max_chars: int = 200) -> str:
    """Extract a short readable summary from the first non-code lines."""
    if not markdown:
        return ""
    lines = [
        ln.strip().lstrip("# ").lstrip("> ")
        for ln in markdown.splitlines()
        if ln.strip() and not ln.startswith("```")
    ]
    text = " / ".join(lines[:5])
    return text[:max_chars]


def _format_sse(event: str, data: dict[str, Any], seq: int) -> str:
    body = {**data, "seq": seq}
    return f"event: {event}\ndata: {json.dumps(body, ensure_ascii=False, default=str)}\n\n"


def packet_to_research_state(pkt: EscalationPacket, *, request_id: str) -> ResearchState:
    """Convert confirmed EscalationPacket into ResearchState (E13)."""
    return ResearchState(
        user_id="anonymous",
        session_id=request_id,
        user_message=pkt.explicit_task.raw_last_user_turn,
        request_id=request_id,
        target_ts_code=pkt.explicit_task.target_ts_code,
        target_entity=pkt.explicit_task.target_entity_name,
        chat_extracted_entities=list(pkt.chat_derived_signals.entities),
        chat_extracted_preferences=list(pkt.chat_derived_signals.preferences),
        chat_known_tool_results=list(pkt.known_facts.tool_results),
        chat_session_id=pkt.session_metadata.chat_session_id,
    )


@router.post("/escalate")
async def escalate(
    req: EscalateRequest,
    record_repo: EscalationRecordRepo = Depends(get_escalation_record_repo),
    research_agent: ResearchAgent = Depends(get_research_agent),
    chat_session_repo: ChatSessionRepo = Depends(get_chat_session_repo),
    research_report_repo: ResearchReportRepo = Depends(get_research_report_repo),
) -> StreamingResponse:
    """Receive confirmed packet, persist diff, invoke ResearchAgent, stream events."""

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

        # 2. Build ResearchState and invoke ResearchAgent (E13)
        request_id = f"esc:{uuid4().hex[:16]}"
        state = packet_to_research_state(req.packet_confirmed, request_id=request_id)

        try:
            await record_repo.update_status(req.draft_record_id, status="running")
            sut_out = await research_agent.run(
                user_input=state.user_message,
                request_id=request_id,
                state_overrides={
                    "target_ts_code": state.target_ts_code,
                    "target_entity": state.target_entity,
                    "chat_extracted_entities": state.chat_extracted_entities,
                    "chat_extracted_preferences": state.chat_extracted_preferences,
                    "chat_known_tool_results": state.chat_known_tool_results,
                    "chat_session_id": state.chat_session_id,
                },
            )
        except Exception as e:
            logger.exception("escalate: research_agent.run failed")
            await record_repo.update_status(
                req.draft_record_id,
                status="failed",
                error_msg=str(e),
            )
            seq["n"] += 1
            yield _format_sse(
                "escalate_error",
                {"error": str(e), "draft_record_id": str(req.draft_record_id)},
                seq["n"],
            )
            return

        # 3. Double-write report (E13/E14)
        try:
            target_name = (
                req.packet_confirmed.explicit_task.target_entity_name
                or req.packet_confirmed.explicit_task.target_ts_code
                or "Unknown"
            )
            rpt_row = await research_report_repo.create_from_sut_output(
                target_name=target_name,
                target_ts_code=req.packet_confirmed.explicit_task.target_ts_code,
                report_markdown=sut_out.response_text,
                request_id=request_id,
                source_chat_session_id=req.packet_confirmed.session_metadata.chat_session_id,
            )
            summary = _summarize_report(sut_out.response_text)
            await chat_session_repo.append_message(
                session_id=req.packet_confirmed.session_metadata.chat_session_id,
                role="assistant",
                content=f"[研报已生成: {target_name}]",
                message_type="research_report",
                research_report_id=rpt_row.id,
                research_report_summary=summary,
            )
            await record_repo.attach_research_report(
                req.draft_record_id,
                research_report_id=rpt_row.id,
            )
            await record_repo.update_status(req.draft_record_id, status="completed")
        except Exception as e:
            logger.exception("escalate: double-write failed")
            await record_repo.update_status(
                req.draft_record_id,
                status="failed",
                error_msg=f"double-write failed: {e}",
            )
            seq["n"] += 1
            yield _format_sse(
                "escalate_error",
                {"error": str(e), "draft_record_id": str(req.draft_record_id)},
                seq["n"],
            )
            return

        seq["n"] += 1
        yield _format_sse(
            "escalate_done",
            {
                "draft_record_id": str(req.draft_record_id),
                "research_report_id": rpt_row.id,
                "report_summary": summary,
                "request_id": request_id,
            },
            seq["n"],
        )

    return StreamingResponse(_stream(), media_type="text/event-stream")
