"""C70 regression — a research report stuck at 'streaming' is rescued to 'failed'.

When _stream_research raises mid-stream (after the row was created at 'streaming'),
the except block must open a FRESH session and UPDATE the row to 'failed' so it
doesn't sit at 'streaming' forever.

The rescue intentionally uses a separate connection, so this test commits the row
to the real test DB (it cannot use the savepoint-isolated db_session fixture, whose
uncommitted row would be invisible to the fresh rescue session) and cleans it up.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from app.core.database import Base, SessionLocal, engine
from app.models.research_report import ResearchReport

pytestmark = pytest.mark.integration


class _FakeReq:
    """Minimal request stand-in for _stream_research_with_persist."""

    target_name: str = "x"
    target_ts_code: str = "000001.SZ"
    user_message: str = "test"
    enable_web_search: bool = False
    enable_kb_search: bool = False


def test_c70_stuck_row_rescued_on_stream_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    Base.metadata.create_all(bind=engine)
    report_id = f"c70-{uuid.uuid4().hex[:8]}"

    # Seed the 'streaming' row with a real committed session (the rescue uses a
    # separate connection and must be able to see it).
    setup = SessionLocal()
    try:
        setup.add(
            ResearchReport(
                id=report_id,
                user_id="u-c70",
                status="streaming",
                target_name="x",
                target_ts_code="000001.SZ",
                request_id="req-c70",
            )
        )
        setup.commit()
    finally:
        setup.close()

    from app.router import reports as reports_mod

    async def _boom_stream(*_a: Any, **_kw: Any) -> Any:
        raise RuntimeError("stream boom")
        yield  # pragma: no cover — makes this an async generator

    monkeypatch.setattr(reports_mod, "_stream_research", _boom_stream)

    persist_db = SessionLocal()
    try:

        async def _drive() -> None:
            async for _ in reports_mod._stream_research_with_persist(
                report_id=report_id,
                req=_FakeReq(),
                db=persist_db,
                user_id="u-c70",
            ):
                pass

        asyncio.run(_drive())
    finally:
        persist_db.close()

    verify = SessionLocal()
    try:
        row = verify.get(ResearchReport, report_id)
        assert row is not None
        assert row.status == "failed"  # rescued, not stuck at 'streaming'
    finally:
        # This test commits to the real test DB (no savepoint isolation) — clean up.
        stale = verify.get(ResearchReport, report_id)
        if stale is not None:
            verify.delete(stale)
            verify.commit()
        verify.close()
