"""L0 — ChatMemoryCalibrationRun ORM(audit 表 schema, spec § 11 末尾 #3)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.models.memory_calibration import ChatMemoryCalibrationRun


def test_orm_construction() -> None:
    run = ChatMemoryCalibrationRun(
        run_id=uuid4(),
        started_at=datetime.now(UTC),
        finished_at=None,
        scanned_edges=0,
        promoted_to_high=0,
        demoted_to_medium=0,
        overridden_to_low=0,
        status="running",
    )
    assert run.status == "running"
    assert run.scanned_edges == 0


def test_table_name() -> None:
    assert ChatMemoryCalibrationRun.__tablename__ == "chat_memory_calibration_runs"


def test_required_columns_present() -> None:
    cols = {c.name for c in ChatMemoryCalibrationRun.__table__.columns}
    assert {
        "run_id",
        "started_at",
        "finished_at",
        "scanned_edges",
        "promoted_to_high",
        "demoted_to_medium",
        "overridden_to_low",
        "status",
        "error_message",
    }.issubset(cols)


def test_run_id_is_primary_key() -> None:
    pk_cols = {c.name for c in ChatMemoryCalibrationRun.__table__.primary_key.columns}
    assert pk_cols == {"run_id"}
