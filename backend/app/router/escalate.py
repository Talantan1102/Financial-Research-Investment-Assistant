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
from app.services.escalation_record_repo import EscalationRecordRepo
from app.services.research_report_repo import ResearchReportRepo
from app.services.run_escalation_repo import RunEscalationRepo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v0/chat", tags=["chat-escalate-legacy"])
research_router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/research-escalations",
    tags=["research-escalations"],
)


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
    source_run_id: uuid.UUID | None = None
    source_session_id: uuid.UUID | None = None


# C43: SSOT — get_escalation_record_repo is defined once in chat.py; re-export it
# here so app_main needs only one dependency_override (not two identical stubs).
def get_escalation_record_repo() -> EscalationRecordRepo:
    """Run/research-owned provider, independent of the legacy chat router."""
    raise RuntimeError("EscalationRecordRepo dependency not configured")


def get_research_agent() -> ResearchAgent:
    raise RuntimeError("ResearchAgent dependency not configured")


def get_chat_session_repo() -> RunEscalationRepo:
    """Compatibility dependency name; implementation is Run-native."""
    raise RuntimeError("RunEscalationRepo dependency not configured")


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


async def _session_owned_by(
    chat_session_repo: RunEscalationRepo, session_id: str, user: User
) -> bool:
    """True iff ``session_id`` resolves to a chat session owned by ``user``.

    非 UUID / 不存在的 session_id 一律 False(get_session 内部 uuid.UUID() 解析)。
    """
    try:
        sess = await chat_session_repo.get_session(session_id)
    except (ValueError, AttributeError, TypeError):
        return False
    return sess is not None and str(sess.user_id) == str(user.id)


async def _source_context_allowed(
    *,
    record: Any,
    req: EscalateRequest,
    tenant_id: uuid.UUID | None,
    user: User,
    chat_session_repo: RunEscalationRepo,
) -> bool:
    """Fail closed for a supplied Run/Session provenance reference.

    The legacy route has no tenant path, so the repository is the source of
    truth there.  New callers provide optional ``get_run``/
    ``session_belongs_to_tenant`` methods; both are checked when available.
    """
    record_tenant = getattr(record, "tenant_id", None)
    if tenant_id is not None and record_tenant is not None and str(record_tenant) != str(tenant_id):
        return False
    source_sid = req.source_session_id or req.packet_confirmed.session_metadata.chat_session_id
    if req.source_session_id is not None and str(req.source_session_id) != str(req.packet_confirmed.session_metadata.chat_session_id):
        return False
    if tenant_id is not None:
        membership_check = getattr(chat_session_repo, "session_belongs_to_tenant", None)
        if membership_check is not None:
            allowed = membership_check(source_sid, tenant_id, user.id)
            if hasattr(allowed, "__await__"):
                allowed = await allowed
            if not allowed:
                return False
    source_run_id = req.source_run_id
    if source_run_id is not None:
        get_run = getattr(chat_session_repo, "get_run", None)
        if get_run is None:
            # Do not allow an unresolvable run to be written as provenance.
            return False
        run = get_run(source_run_id)
        if hasattr(run, "__await__"):
            run = await run
        if run is None or str(getattr(run, "session_id", "")) != str(source_sid):
            return False
        if tenant_id is not None and str(getattr(run, "tenant_id", "")) != str(tenant_id):
            return False
        if str(getattr(run, "created_by_user_id", user.id)) != str(user.id):
            return False
    return True


@research_router.post("")
@router.post("/escalate")
async def escalate(
    req: EscalateRequest,
    tenant_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user_required),
    record_repo: EscalationRecordRepo = Depends(get_escalation_record_repo),
    research_agent: ResearchAgent = Depends(get_research_agent),
    chat_session_repo: RunEscalationRepo = Depends(get_chat_session_repo),
    research_report_repo: ResearchReportRepo = Depends(get_research_report_repo),
) -> StreamingResponse:
    """Receive confirmed packet, persist diff, invoke ResearchAgent, stream events.

    数据隔离:draft record 的会话 + packet 指定的 chat_session_id 都必须属于当前
    用户(record 本身无 user_id,归属经 session_id → chat_sessions.user_id)。
    防越权触发研报/改记录 + 防把 assistant 消息注入他人会话。不符一律 404
    (与 chat/chats/reports 同一隔离范式,内联 str 比对)。
    """
    record = await record_repo.get(req.draft_record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="escalation record not found")
    candidate_sids = {
        str(record.session_id),
        str(req.packet_confirmed.session_metadata.chat_session_id),
    }
    for sid in candidate_sids:
        if not await _session_owned_by(chat_session_repo, sid, user):
            raise HTTPException(status_code=404, detail="escalation record not found")
    if not await _source_context_allowed(
        record=record,
        req=req,
        tenant_id=tenant_id,
        user=user,
        chat_session_repo=chat_session_repo,
    ):
        raise HTTPException(status_code=404, detail="escalation record not found")
    source_session_id = req.source_session_id or req.packet_confirmed.session_metadata.chat_session_id

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
                source_chat_session_id=None,
                source_session_id=source_session_id,
                source_run_id=req.source_run_id,
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
