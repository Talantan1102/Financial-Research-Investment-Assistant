"""L1 Integration — posterior_calibration_weekly task body + audit 写库(spec § 11 末尾 #3).

Task 11 (Plan 5): 端到端验证 posterior_calibration_weekly task body 接 run_weekly_calibration
+ 写 ChatMemoryCalibrationRun audit row.

Plan 3 retrieval_logs/feedback 表 schema 已 ship (契约 § 17 A4); 本 test 用 Reader/Updater
Protocol mock 解耦 SQL 细节, 验证 task wiring 正确.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from app.memory.posterior_calibration import EdgeCalibrationInput
from app.models.memory_calibration import ChatMemoryCalibrationRun

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def celery_eager(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    monkeypatch.setenv("CELERY_TASK_EAGER_PROPAGATES", "1")


class _FakeReader:
    def __init__(self, edges: list[EdgeCalibrationInput]) -> None:
        self._edges = edges

    def fetch_edge_metrics(
        self, since: datetime, until: datetime
    ) -> Iterable[EdgeCalibrationInput]:
        return iter(self._edges)


class _FakeUpdater:
    def __init__(self) -> None:
        self.updates: list[tuple[UUID, float]] = []

    def update_importance(self, edge_id: UUID, new_importance: float) -> None:
        self.updates.append((edge_id, new_importance))


def test_posterior_calibration_task_writes_audit_row() -> None:
    """Task 跑完 audit 写 1 行 + scanned/promoted/overridden 计数对."""
    edges = [
        EdgeCalibrationInput(
            uuid4(), 0.5, retrieve_hits_7d=10, user_overrides_7d=0
        ),  # promote → 0.9
        EdgeCalibrationInput(
            uuid4(), 0.2, retrieve_hits_7d=8, user_overrides_7d=0
        ),  # promote → 0.5
        EdgeCalibrationInput(
            uuid4(), 0.9, retrieve_hits_7d=20, user_overrides_7d=1
        ),  # override → 0.2
        EdgeCalibrationInput(uuid4(), 0.5, retrieve_hits_7d=2, user_overrides_7d=0),  # no_change
    ]
    reader = _FakeReader(edges)
    updater = _FakeUpdater()
    audit_rows: list[ChatMemoryCalibrationRun] = []

    def fake_audit_writer(run: ChatMemoryCalibrationRun) -> None:
        audit_rows.append(run)

    from app.tasks import memory as memory_tasks

    with (
        patch.object(memory_tasks, "_build_calibration_reader", return_value=reader),
        patch.object(memory_tasks, "_build_calibration_updater", return_value=updater),
        patch.object(memory_tasks, "_write_calibration_audit", side_effect=fake_audit_writer),
    ):
        result = memory_tasks.posterior_calibration_weekly.apply().get()

    assert result["scanned_edges"] == 4
    assert result["promoted_to_high"] == 1
    assert result["promoted_to_medium"] == 1
    assert result["overridden_to_low"] == 1
    assert result["status"] == "success"
    assert len(updater.updates) == 3, "no_change edge 不写 update"
    assert len(audit_rows) == 1
    assert audit_rows[0].scanned_edges == 4
    assert audit_rows[0].promoted_to_high == 1
    assert audit_rows[0].demoted_to_medium == 1
    assert audit_rows[0].overridden_to_low == 1
    assert audit_rows[0].status == "success"


def test_posterior_calibration_task_empty_run() -> None:
    """Reader 返回空 → audit row scanned=0, status=success."""
    reader = _FakeReader([])
    updater = _FakeUpdater()
    audit_rows: list[ChatMemoryCalibrationRun] = []

    def fake_audit_writer(run: ChatMemoryCalibrationRun) -> None:
        audit_rows.append(run)

    from app.tasks import memory as memory_tasks

    with (
        patch.object(memory_tasks, "_build_calibration_reader", return_value=reader),
        patch.object(memory_tasks, "_build_calibration_updater", return_value=updater),
        patch.object(memory_tasks, "_write_calibration_audit", side_effect=fake_audit_writer),
    ):
        result = memory_tasks.posterior_calibration_weekly.apply().get()

    assert result["scanned_edges"] == 0
    assert result["status"] == "success"
    assert len(audit_rows) == 1
    assert audit_rows[0].scanned_edges == 0


def test_posterior_calibration_task_default_placeholder_no_crash() -> None:
    """无 patch 时(默认 _build_calibration_reader 返空 reader)task 仍跑成功不抛."""
    from app.tasks import memory as memory_tasks

    result: dict[str, Any] = memory_tasks.posterior_calibration_weekly.apply().get()
    assert result["status"] == "success"
    assert result["scanned_edges"] == 0
