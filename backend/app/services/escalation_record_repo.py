"""EscalationRecordRepo — CRUD for the chat→research handoff trace (E12)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.escalation_record import EscalationRecord


class EscalationRecordRepo:
    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._sf = session_factory

    async def create_draft(
        self,
        *,
        session_id: uuid.UUID | str,
        packet_draft: dict[str, Any],
    ) -> EscalationRecord:
        async with self._sf() as sess:
            row = EscalationRecord(
                id=uuid.uuid4(),
                session_id=session_id,
                packet_draft=packet_draft,
                status="draft",
            )
            sess.add(row)
            await sess.commit()
            await sess.refresh(row)
            return row

    async def get(self, record_id: uuid.UUID | str) -> EscalationRecord | None:
        async with self._sf() as sess:
            return await sess.get(EscalationRecord, record_id)

    async def record_confirmation(
        self,
        *,
        record_id: uuid.UUID | str,
        packet_confirmed: dict[str, Any],
        user_edits: list[dict[str, Any]],
    ) -> None:
        async with self._sf() as sess:
            await sess.execute(
                update(EscalationRecord)
                .where(EscalationRecord.id == record_id)
                .values(
                    packet_confirmed=packet_confirmed,
                    user_edits=user_edits,
                    status="confirmed",
                    confirmed_at=datetime.now(UTC),
                )
            )
            await sess.commit()

    async def attach_research_report(
        self,
        record_id: uuid.UUID | str,
        *,
        research_report_id: str,
    ) -> None:
        async with self._sf() as sess:
            await sess.execute(
                update(EscalationRecord)
                .where(EscalationRecord.id == record_id)
                .values(research_report_id=research_report_id)
            )
            await sess.commit()

    async def update_status(
        self,
        record_id: uuid.UUID | str,
        *,
        status: str,
        error_msg: str | None = None,
    ) -> None:
        values: dict[str, Any] = {"status": status}
        if status in ("completed", "failed"):
            values["completed_at"] = datetime.now(UTC)
        if error_msg:
            values["error_msg"] = error_msg[:2048]
        async with self._sf() as sess:
            await sess.execute(
                update(EscalationRecord).where(EscalationRecord.id == record_id).values(**values)
            )
            await sess.commit()
