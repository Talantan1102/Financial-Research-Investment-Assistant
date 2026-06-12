"""POST /api/v0/chat/escalate — confirmed escalation packet handler.

Receives user-confirmed EscalationPacket, persists diff to EscalationRecord,
invokes ResearchAgent and streams escalate_done event (E13).
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agents.escalation_confidence import compute_confidence
from app.agents.escalation_protocol import EscalationPacket, FieldEdit
from app.agents.research_agent import ResearchAgent
from app.agents.schemas import ResearchState
from app.models.user import User
from app.router.auth_router import get_current_user_required
from app.services.chat_session_repo import ChatSessionRepo
from app.services.escalation_record_repo import EscalationRecordRepo
from app.services.research_report_repo import ResearchReportRepo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v0/chat", tags=["chat-escalate"])


ESCALATION_CONFIDENCE_THRESHOLD_DEFAULT = 0.7


def get_confidence_threshold() -> float:
    """Read ESCALATION_CONFIDENCE_THRESHOLD env var, fall back to default.

    Invalid env values (not parseable as float) fall back to the default but
    log a warning (C47) — an operator typo shouldn't break the router, but it
    must not silently run escalation gating at the wrong threshold either.
    """
    raw = os.getenv("ESCALATION_CONFIDENCE_THRESHOLD")
    if raw is None:
        return ESCALATION_CONFIDENCE_THRESHOLD_DEFAULT
    try:
        return float(raw)
    except ValueError:
        logger.warning(
            "Invalid ESCALATION_CONFIDENCE_THRESHOLD=%r (not a float); using default %.2f",
            raw,
            ESCALATION_CONFIDENCE_THRESHOLD_DEFAULT,
        )
        return ESCALATION_CONFIDENCE_THRESHOLD_DEFAULT


class EscalateRequest(BaseModel):
    draft_record_id: uuid.UUID | str
    packet_confirmed: EscalationPacket
    user_edits: list[FieldEdit] = Field(default_factory=list)


# C43: SSOT — get_escalation_record_repo is defined once in chat.py; re-export it
# here so app_main needs only one dependency_override (not two identical stubs).
from app.router.chat import get_escalation_record_repo  # noqa: E402


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


def packet_to_research_state(
    pkt: EscalationPacket,
    *,
    request_id: str,
    chat_history: list[Any] | None = None,
) -> ResearchState:
    """Convert confirmed EscalationPacket into ResearchState (E13 + v1.x § 6.7).

    Confidence-gated distillation injection (v1.x):
      L1: compute_confidence(pkt, history, ...) ≥ ESCALATION_CONFIDENCE_THRESHOLD
          → populate escalation_intent/discussion_focus/explicit_exclusions on state.
      L3 (raw fallback): otherwise leave distilled fields empty;
          user_message stays as raw_last_user_turn (form-style entry semantics).

    TODO(v1.x+): L2 summary fallback — call LLM to summarize last 3 chat turns
    when conf is "borderline". Currently skipped to keep router lean; add when
    dogfood shows borderline-conf cases need rescue.

    Args:
      pkt: User-confirmed EscalationPacket from chat→DD button.
      request_id: Trace request id.
      chat_history: Optional list of chat messages (each with .content). When
          None, distilled fields are not populated (safe-default — treats
          missing context as low-confidence path).
    """
    state = ResearchState(
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

    if chat_history is None:
        return state

    threshold = get_confidence_threshold()
    conf = compute_confidence(
        extracted=pkt,
        chat_history=chat_history,
        target_ts_code=pkt.explicit_task.target_ts_code or "",
        target_name=pkt.explicit_task.target_entity_name or "",
        user_confirmed_escalation=True,  # entry is from explicit confirm button
    )

    if conf >= threshold:
        return state.model_copy(
            update={
                "escalation_intent": pkt.escalation_intent,
                "discussion_focus": list(pkt.discussion_focus),
                "explicit_exclusions": list(pkt.explicit_exclusions),
            }
        )

    # L3 fallback — state stays form-style (user_message = raw_last_user_turn)
    return state


@router.post("/escalate")
async def escalate(
    req: EscalateRequest,
    user: User = Depends(get_current_user_required),
    record_repo: EscalationRecordRepo = Depends(get_escalation_record_repo),
    research_agent: ResearchAgent = Depends(get_research_agent),
    chat_session_repo: ChatSessionRepo = Depends(get_chat_session_repo),
    research_report_repo: ResearchReportRepo = Depends(get_research_report_repo),
) -> StreamingResponse:
    """Receive confirmed packet, persist diff, invoke ResearchAgent, stream events."""
    # C.6: 校验 chat 会话归属(防匿名升级 + 防往他人会话写研报消息)。
    _csid = req.packet_confirmed.session_metadata.chat_session_id
    _sess = await chat_session_repo.get_session(str(_csid))
    if _sess is None or str(_sess.user_id) != str(user.id):
        raise HTTPException(status_code=404, detail="chat session not found")

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

        # 2. Build ResearchState and stream ResearchAgent events (E13/E15)
        request_id = f"esc:{uuid4().hex[:16]}"
        # TODO(v1.x+): fetch chat history from chat_session_repo here and pass
        # to packet_to_research_state(chat_history=...) so confidence-gating
        # can populate distilled fields. Currently history=None → safe-default
        # path (distilled empty). User can override via direct API.
        state = packet_to_research_state(req.packet_confirmed, request_id=request_id)

        sut_out = None
        try:
            await record_repo.update_status(req.draft_record_id, status="running")
            async for evt in research_agent.run_streaming(
                user_input=state.user_message,
                request_id=request_id,
                state_overrides={
                    "target_ts_code": state.target_ts_code,
                    "target_entity": state.target_entity,
                    "chat_extracted_entities": state.chat_extracted_entities,
                    "chat_extracted_preferences": state.chat_extracted_preferences,
                    "chat_known_tool_results": state.chat_known_tool_results,
                    "chat_session_id": state.chat_session_id,
                    # v1.x distilled (populated only when confidence ≥ threshold)
                    "escalation_intent": state.escalation_intent,
                    "discussion_focus": state.discussion_focus,
                    "explicit_exclusions": state.explicit_exclusions,
                },
            ):
                if evt["event"] == "_final_sut_output":
                    sut_out = evt["data"]
                    continue
                seq["n"] += 1
                yield _format_sse(evt["event"], evt["data"], seq["n"])
        except Exception as e:
            logger.exception("escalate: research_agent.run_streaming failed")
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

        if sut_out is None:
            seq["n"] += 1
            yield _format_sse(
                "escalate_error",
                {
                    "error": "research stream ended without final output",
                    "draft_record_id": str(req.draft_record_id),
                },
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
