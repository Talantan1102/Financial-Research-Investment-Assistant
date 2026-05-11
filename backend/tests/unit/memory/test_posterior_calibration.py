"""L0 — posterior_calibration.calibrate_importance / decide_calibration_action.

spec § 11 末尾 #3 算法深度补丁: importance 三档反向校准.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from uuid import UUID, uuid4

from app.memory.posterior_calibration import (
    EdgeCalibrationInput,
    calibrate_importance,
    decide_calibration_action,
    run_weekly_calibration,
)


def test_high_hits_promote_medium_to_high() -> None:
    """高命中(≥5)且无否决 → 0.5 → 0.9."""
    edge = EdgeCalibrationInput(
        edge_id=uuid4(),
        importance=0.5,
        retrieve_hits_7d=8,
        user_overrides_7d=0,
    )
    new_imp, action = calibrate_importance(edge)
    assert new_imp == 0.9
    assert action == "promoted_to_high"


def test_high_hits_promote_low_to_medium() -> None:
    edge = EdgeCalibrationInput(
        edge_id=uuid4(),
        importance=0.2,
        retrieve_hits_7d=10,
        user_overrides_7d=0,
    )
    new_imp, action = calibrate_importance(edge)
    assert new_imp == 0.5
    assert action == "promoted_to_medium"


def test_user_override_demote_to_low() -> None:
    """用户否决 → 直接 0.2, 无视命中数."""
    edge = EdgeCalibrationInput(
        edge_id=uuid4(),
        importance=0.9,
        retrieve_hits_7d=20,
        user_overrides_7d=1,
    )
    new_imp, action = calibrate_importance(edge)
    assert new_imp == 0.2
    assert action == "overridden_to_low"


def test_neutral_no_change() -> None:
    edge = EdgeCalibrationInput(
        edge_id=uuid4(),
        importance=0.5,
        retrieve_hits_7d=2,
        user_overrides_7d=0,
    )
    new_imp, action = calibrate_importance(edge)
    assert new_imp == 0.5
    assert action == "no_change"


def test_already_max_no_promote() -> None:
    edge = EdgeCalibrationInput(
        edge_id=uuid4(),
        importance=0.9,
        retrieve_hits_7d=20,
        user_overrides_7d=0,
    )
    new_imp, action = calibrate_importance(edge)
    assert new_imp == 0.9
    assert action == "no_change"


def test_already_min_no_demote() -> None:
    edge = EdgeCalibrationInput(
        edge_id=uuid4(),
        importance=0.2,
        retrieve_hits_7d=0,
        user_overrides_7d=0,
    )
    new_imp, action = calibrate_importance(edge)
    assert new_imp == 0.2
    assert action == "no_change"


def test_already_low_with_override_no_change() -> None:
    """已 low 且 override → 仍是 low, 标 no_change(不重复降级)."""
    edge = EdgeCalibrationInput(
        edge_id=uuid4(),
        importance=0.2,
        retrieve_hits_7d=0,
        user_overrides_7d=2,
    )
    new_imp, action = calibrate_importance(edge)
    assert new_imp == 0.2
    assert action == "no_change"


def test_decide_calibration_action_threshold() -> None:
    """命中阈值 = 5(可调常量)."""
    assert decide_calibration_action(retrieve_hits=4, overrides=0)[0] == "no_change"
    assert decide_calibration_action(retrieve_hits=5, overrides=0)[0] == "promote"
    assert decide_calibration_action(retrieve_hits=100, overrides=1)[0] == "override_to_low"


# === run_weekly_calibration 集成 ===


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


def test_run_weekly_calibration_aggregates_4_actions() -> None:
    edges = [
        EdgeCalibrationInput(
            uuid4(), 0.5, retrieve_hits_7d=10, user_overrides_7d=0
        ),  # promote_high
        EdgeCalibrationInput(
            uuid4(), 0.2, retrieve_hits_7d=8, user_overrides_7d=0
        ),  # promote_medium
        EdgeCalibrationInput(
            uuid4(), 0.9, retrieve_hits_7d=20, user_overrides_7d=1
        ),  # override_low
        EdgeCalibrationInput(uuid4(), 0.5, retrieve_hits_7d=2, user_overrides_7d=0),  # no_change
    ]
    reader = _FakeReader(edges)
    updater = _FakeUpdater()
    result = run_weekly_calibration(reader=reader, updater=updater)

    assert result.scanned_edges == 4
    assert result.promoted_to_high == 1
    assert result.demoted_to_medium == 1  # column name 沿用 spec, 实是 promoted_to_medium
    assert result.overridden_to_low == 1
    assert len(updater.updates) == 3, "no_change edge 不写 update"


def test_run_weekly_calibration_empty_input() -> None:
    reader = _FakeReader([])
    updater = _FakeUpdater()
    result = run_weekly_calibration(reader=reader, updater=updater)
    assert result.scanned_edges == 0
    assert result.promoted_to_high == 0
    assert len(updater.updates) == 0
