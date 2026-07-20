"""Contract tests for the read-only Run metrics projection.

The production fixture runs these queries against PostgreSQL; this focused test
keeps the contract fast and deterministic by supplying aggregate result rows.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.services.run_metrics import RunMetricsService


class _Result:
    def __init__(self, rows=(), scalar=None):
        self._rows = rows
        self._scalar = scalar

    def all(self):
        return self._rows

    def one(self):
        return self._rows[0]

    def scalar_one(self):
        return self._scalar


class _Session:
    def __init__(self):
        self.statements = []
        self._results = iter([
            _Result([("completed", 2), ("queued", 1)]),
            _Result([SimpleNamespace(depth=1, oldest=None, wait=4.5)]),
            _Result([SimpleNamespace(scheduling=1.2, no_slot=1)]),
            _Result([("completed", 2)]),
            _Result([("online", 1, 2, None)]),
            _Result([(uuid4(), 1)]),
            _Result(scalar=0),
            _Result([SimpleNamespace(backlog=1, retries=2)]),
            _Result([("waiting_input", 1)]),
            _Result([(15, 0.25)]),
            _Result(scalar=3.0),
        ])

    async def execute(self, statement):
        self.statements.append(statement)
        return next(self._results)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


@pytest.mark.asyncio
async def test_metrics_are_aggregate_read_only_projection():
    session = _Session()

    class _Factory:
        def __call__(self):
            return session

    result = await RunMetricsService(_Factory()).snapshot(uuid4())
    assert result["runs"]["counts"] == {"completed": 2, "queued": 1}
    assert result["runs"]["queue_depth"] == 1
    assert result["scheduling"]["no_slot"] == 1
    assert result["outbox"] == {"backlog": 1, "retries": 2}
    assert result["usage"] == {"total_tokens": 15, "cost_cny": 0.25}
    assert len(session.statements) == 11
    assert not any(getattr(statement, "is_update", False) for statement in session.statements)
