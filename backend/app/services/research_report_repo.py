"""ResearchReportRepo — minimal CRUD for escalate router (Plan 3 / E13-E14)."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.research_report import ResearchReport


class ResearchReportRepo:
    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._sf = session_factory

    async def create_from_sut_output(
        self,
        *,
        target_name: str,
        target_ts_code: str | None,
        report_markdown: str,
        request_id: str,
        source_chat_session_id: object,
        cost: Decimal = Decimal("0"),
    ) -> ResearchReport:
        """Persist a completed research report from escalation SUTOutput.

        ResearchReport.id is VARCHAR(64); we use "rpt-{hex16}" prefix string.
        source_chat_session_id is UUID (chat_sessions.id FK, nullable).
        """
        import uuid as _uuid

        async with self._sf() as sess:
            rid = f"rpt-{uuid4().hex[:16]}"
            # Normalise source_chat_session_id to UUID object if given as str
            if isinstance(source_chat_session_id, str):
                try:
                    source_chat_session_id = _uuid.UUID(source_chat_session_id)
                except ValueError:
                    source_chat_session_id = None
            row = ResearchReport(
                id=rid,
                target_name=target_name,
                target_ts_code=target_ts_code,
                status="completed",
                report_json={"markdown": report_markdown},
                cost=cost,
                request_id=request_id,
                source_chat_session_id=source_chat_session_id,
            )
            sess.add(row)
            await sess.commit()
            await sess.refresh(row)
            return row
