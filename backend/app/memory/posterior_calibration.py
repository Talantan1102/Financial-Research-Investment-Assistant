"""Posterior calibration weekly job(spec § 11 末尾 #3 算法深度补丁).

类比 YouTube/TikTok ranking 系统的 "prediction + posterior calibration":
LLM 一次抽完 importance 不动, 周 job 根据行为信号反向调:
  - 高命中(过去 7 天 retrieve 命中 ≥ 5 且无否决)→ 升档
  - 用户否决(user_overrides) → 直接 low
  - 中性 → 不动

importance 三档边界(spec § 2 schema CHECK constraint): 0.9 / 0.5 / 0.2.
Plan 3 落 retrieve 命中 + 用户否决 instrumentation (chat_memory_retrieval_logs +
chat_memory_retrieval_feedback, 契约 § 17 A4), Plan 5 weekly job 消费.

Reader / Updater 用 Protocol 抽象, 真 SQL 走 thin adapter (Plan 5 task 11 接 task body).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

# spec § 11 末尾 #3 校准阈值(本 plan 落地默认值, 后续 v1.x 调参)
HIT_THRESHOLD = 5  # 7 天命中数 ≥ 5 视为高频
OBSERVATION_WINDOW_DAYS = 7

# importance 三档(spec § 2 + § 11 #3)
IMPORTANCE_HIGH = 0.9
IMPORTANCE_MEDIUM = 0.5
IMPORTANCE_LOW = 0.2


@dataclass
class EdgeCalibrationInput:
    """Plan 3 instrumentation 表抽出的单 edge 行为信号."""

    edge_id: UUID
    importance: float
    retrieve_hits_7d: int
    user_overrides_7d: int


@dataclass
class CalibrationRunResult:
    """run_weekly_calibration 输出, audit 表写入字段镜像."""

    run_id: UUID
    started_at: datetime
    finished_at: datetime | None
    scanned_edges: int
    promoted_to_high: int
    demoted_to_medium: int  # column 沿用 spec, 实际语义是 promoted_low_to_medium
    overridden_to_low: int


class RetrievalEventReader(Protocol):
    """Plan 3 落库的 instrumentation reader.

    Plan 5 通过 Protocol 隔离, Plan 3 schema 漂移加 thin adapter 即可.
    Plan 3 ship 表名: chat_memory_retrieval_logs + chat_memory_retrieval_feedback.
    """

    def fetch_edge_metrics(
        self, since: datetime, until: datetime
    ) -> Iterable[EdgeCalibrationInput]: ...


class EdgeImportanceUpdater(Protocol):
    """写端 Protocol — 真实现走 SQLAlchemy session.update."""

    def update_importance(self, edge_id: UUID, new_importance: float) -> None: ...


def decide_calibration_action(retrieve_hits: int, overrides: int) -> tuple[str, float | None]:
    """Returns (action, target_importance_or_None).

    action ∈ {"no_change", "promote", "override_to_low"}.
    target_importance None 表示让 caller 按 current 档位算下一档.
    """
    if overrides > 0:
        return "override_to_low", IMPORTANCE_LOW
    if retrieve_hits >= HIT_THRESHOLD:
        return "promote", None
    return "no_change", None


def calibrate_importance(edge: EdgeCalibrationInput) -> tuple[float, str]:
    """Returns (new_importance, action_label).

    action_label ∈ {"no_change", "promoted_to_high", "promoted_to_medium", "overridden_to_low"}.
    """
    action, _target = decide_calibration_action(
        retrieve_hits=edge.retrieve_hits_7d,
        overrides=edge.user_overrides_7d,
    )

    if action == "override_to_low":
        if edge.importance == IMPORTANCE_LOW:
            return edge.importance, "no_change"
        return IMPORTANCE_LOW, "overridden_to_low"

    if action == "promote":
        if edge.importance == IMPORTANCE_LOW:
            return IMPORTANCE_MEDIUM, "promoted_to_medium"
        if edge.importance == IMPORTANCE_MEDIUM:
            return IMPORTANCE_HIGH, "promoted_to_high"
        return edge.importance, "no_change"  # already high

    return edge.importance, "no_change"


def run_weekly_calibration(
    *,
    reader: RetrievalEventReader,
    updater: EdgeImportanceUpdater,
    now: datetime | None = None,
) -> CalibrationRunResult:
    """Plan 5 task posterior_calibration_weekly 入口.

    扫过去 7 天 instrumentation, 反向调 importance, 写 calibration_runs audit 表(由 caller).
    """
    started = now if now is not None else datetime.now(UTC)
    since = started - timedelta(days=OBSERVATION_WINDOW_DAYS)

    counts: dict[str, int] = {
        "promoted_to_high": 0,
        "promoted_to_medium": 0,
        "overridden_to_low": 0,
        "scanned": 0,
    }

    for edge in reader.fetch_edge_metrics(since=since, until=started):
        counts["scanned"] += 1
        new_imp, action = calibrate_importance(edge)
        if action == "no_change":
            continue
        updater.update_importance(edge.edge_id, new_imp)
        if action in counts:
            counts[action] += 1

    return CalibrationRunResult(
        run_id=uuid4(),
        started_at=started,
        finished_at=datetime.now(UTC),
        scanned_edges=counts["scanned"],
        promoted_to_high=counts["promoted_to_high"],
        demoted_to_medium=counts["promoted_to_medium"],
        overridden_to_low=counts["overridden_to_low"],
    )
