from __future__ import annotations

import logging
from uuid import uuid4

import pytest
from app.processes.run_scheduler import RunScheduler
from app.processes.run_worker import build_run_stream_event_sink
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


@pytest.mark.asyncio
async def test_scheduler_cycle_log_has_opaque_correlation_id(caplog) -> None:
    class _Scheduling:
        async def recover_expired_attempts(self, _limit):
            return ()

        async def schedule_once(self):
            return None

    caplog.set_level(logging.INFO)
    await RunScheduler(_Scheduling(), None).run_cycle()
    record = next(item for item in caplog.records if "scheduler cycle completed" in item.message)
    assert getattr(record, "correlation_id", None)
    assert "prompt" not in record.message.lower()
    assert "token" not in record.message.lower()


@pytest.mark.asyncio
async def test_stream_sink_log_has_run_correlation_id_without_payload(caplog) -> None:
    class _Redis:
        pass

    async def _raise(_event):
        raise RuntimeError("transport failed")

    sink = build_run_stream_event_sink(_Redis())
    sink.__closure__[0].cell_contents.publish = _raise  # type: ignore[attr-defined]
    event = type("Event", (), {"run_id": uuid4(), "attempt_id": uuid4()})()
    caplog.set_level(logging.WARNING)
    await sink(event)
    record = next(item for item in caplog.records if "Run stream event rejected" in item.message)
    assert getattr(record, "run_id", None) == str(event.run_id)
    assert "RuntimeError" in record.message
    assert "transport failed" not in record.message
    assert "prompt" not in record.message.lower()
    assert "token" not in record.message.lower()
