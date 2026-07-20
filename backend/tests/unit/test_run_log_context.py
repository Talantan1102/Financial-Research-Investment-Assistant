from __future__ import annotations

import logging
from uuid import uuid4

from app.services.run_metrics import CorrelationIdFilter, log_context, run_log_context


def test_run_log_context_only_exposes_opaque_correlation_ids(caplog) -> None:  # type: ignore[no-untyped-def]
    run_id, attempt_id, worker_id = uuid4(), uuid4(), uuid4()
    record = logging.LogRecord("run", logging.INFO, __file__, 1, "prompt=%s", ("secret",), None)
    with run_log_context(run_id=run_id, attempt_id=attempt_id, worker_id=worker_id):
        assert log_context() == {
            "run_id": str(run_id),
            "attempt_id": str(attempt_id),
            "worker_id": str(worker_id),
        }
        CorrelationIdFilter().filter(record)
    assert record.run_id == str(run_id)
    assert record.attempt_id == str(attempt_id)
    assert record.worker_id == str(worker_id)
    assert "secret" not in repr(log_context())
    assert "token" not in repr(log_context()).lower()


def test_run_log_context_does_not_leak_between_scopes() -> None:
    assert log_context() == {}
    with run_log_context(run_id="run-a"):
        assert log_context() == {"run_id": "run-a"}
    assert log_context() == {}
