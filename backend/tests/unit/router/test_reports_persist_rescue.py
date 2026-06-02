"""C70 regression — a research report stuck at 'streaming' is rescued to 'failed'.

When the final persist ``db.commit()`` raises, ``_stream_research_with_persist``
must roll back the tainted session and open a FRESH ``SessionLocal`` to flip the
row to 'failed' (no stale-scanner covers research_reports, so otherwise it stays
'streaming' forever).

Pure-unit: the rescue uses a separate connection, so rather than fight the
savepoint-isolated db_session fixture we mock the persist db + the fresh rescue
session and assert the rescue UPDATE is issued and committed.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any, cast
from unittest.mock import MagicMock

import app.router.reports as reports_mod
import pytest


def test_c70_commit_failure_opens_fresh_session_and_marks_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # report stub — only .id / .status / .report_json / .cost / .request_id touched
    report = MagicMock()
    report.id = "c70-test-id"
    report.cost = Decimal("0")

    # persist db whose final commit() raises (rollback is a recorded no-op)
    db = MagicMock()
    db.commit.side_effect = RuntimeError("simulated persist commit failure")

    # fresh rescue session (what SessionLocal() returns in the except path)
    rescue = MagicMock()
    monkeypatch.setattr(reports_mod, "SessionLocal", lambda: rescue)

    async def _fake_stream(*_a: Any, **_kw: Any) -> AsyncIterator[str]:
        yield 'data: {"type":"done","data":{"request_id":"req-c70"}}\n\n'

    monkeypatch.setattr(reports_mod, "_stream_research", _fake_stream)

    async def _run() -> None:
        async for _ in reports_mod._stream_research_with_persist(
            req=cast(Any, MagicMock()),
            user=cast(Any, MagicMock()),
            graph=None,
            report=cast(Any, report),
            db=cast(Any, db),
        ):
            pass

    asyncio.run(_run())

    # The tainted persist session was rolled back...
    db.rollback.assert_called_once()
    # ...and a FRESH session issued the rescue UPDATE + committed + closed it.
    rescue.execute.assert_called_once()
    sql = str(rescue.execute.call_args.args[0])
    assert "status = 'failed'" in sql
    assert "status = 'streaming'" in sql  # only rescue rows still streaming
    assert rescue.execute.call_args.args[1] == {"id": "c70-test-id"}
    rescue.commit.assert_called_once()
    rescue.close.assert_called_once()
