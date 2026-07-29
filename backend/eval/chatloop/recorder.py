"""chatloop 评估结果落库(blueprint § 9 闭环的"存"那半)。

两张专表(不塞进 DD 形状的 backtest_runs):
- chatloop_eval_runs:一次评估跑一行,记**怎么跑的**(模式/模型/采样/阈值/git_sha/
  prompt_sha/耗时/成本/全量 config_json)。
- chatloop_eval_metrics:一次跑 N 行,每个指标一行(behavior × metric × value × 分子/分母)。

复用项目无-alembic 模式:Base.metadata.create_all(checkfirst=True) 幂等建表;
sync SessionLocal(与 EvalRecorder 同源)。成本按**时间窗**从 trace_spans 汇总
(单用户评估无并发,够用;best-effort,失败记 null)。
"""

from __future__ import annotations

import hashlib
import math
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.database import Base, SessionLocal, engine
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from eval.chatloop.artifact_store import ArtifactReference, read_verified_artifact
from eval.chatloop.policy_registry import Violation


class ChatloopEvalRunRow(Base):
    __tablename__ = "chatloop_eval_runs"

    run_id = Column(String(64), primary_key=True)
    created_at = Column(Text, nullable=False)  # ISO
    git_sha = Column(Text, nullable=True)
    mode = Column(String(32), nullable=False)  # ci/offline/grounding/multiturn
    dispatch = Column(String(16), nullable=True)  # noop/real
    sut_model = Column(Text, nullable=True)
    judge_model = Column(Text, nullable=True)
    simulator_model = Column(Text, nullable=True)
    k = Column(Integer, nullable=True)
    max_steps = Column(Integer, nullable=True)
    max_turns = Column(Integer, nullable=True)
    golden_file = Column(Text, nullable=True)
    case_count = Column(Integer, nullable=False, default=0)
    system_prompt_sha = Column(Text, nullable=True)
    thresholds_json = Column(JSONB, nullable=True)
    sampling_json = Column(JSONB, nullable=True)  # {sut/judge/simulator: {temperature,top_p,top_k}}
    duration_ms = Column(Integer, nullable=True)
    cost_cny = Column(Float, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    status = Column(String(32), nullable=False, default="ok")
    config_json = Column(JSONB, nullable=True)  # 全量兜底(复现用)

    __table_args__ = (
        Index("idx_clrun_created", "created_at"),
        Index("idx_clrun_mode", "mode"),
        Index("idx_clrun_sha", "git_sha"),
    )


class ChatloopEvalMetricRow(Base):
    __tablename__ = "chatloop_eval_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), nullable=False)  # → chatloop_eval_runs.run_id
    behavior = Column(String(32), nullable=False)  # routing/tool/abstain/grounding/multiturn...
    layer = Column(String(16), nullable=True)  # ci/offline
    metric = Column(String(48), nullable=False)  # RelAcc/IrrelAcc/strict_faith/goal_met...
    value = Column(Float, nullable=True)
    numerator = Column(Integer, nullable=True)
    denominator = Column(Integer, nullable=True)

    __table_args__ = (
        Index("idx_clmetric_run", "run_id"),
        Index("idx_clmetric_behavior", "behavior"),
    )


class ChatloopEvalTrialRow(Base):
    __tablename__ = "chatloop_eval_trials"

    trial_id = Column(String(64), primary_key=True)
    run_id = Column(String(64), nullable=False)
    case_id = Column(String(32), nullable=False)
    trial_index = Column(Integer, nullable=False)
    suite_type = Column(String(16), nullable=False)
    trial_status = Column(String(32), nullable=False)
    task_pass = Column(Boolean, nullable=True)
    task_score = Column(Float, nullable=True)
    failure_reason = Column(Text, nullable=True)
    artifact_path = Column(Text, nullable=False)
    artifact_sha256 = Column(String(64), nullable=False)
    created_at = Column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "trial_status IN ('valid', 'harness_failed', 'invalid_evidence')",
            name="ck_cltrial_status",
        ),
        CheckConstraint(
            "suite_type IN ('Capability', 'Regression')",
            name="ck_cltrial_suite_type",
        ),
        CheckConstraint("trial_index >= 0", name="ck_cltrial_index_nonnegative"),
        CheckConstraint(
            "task_score IS NULL OR (task_score >= 0 AND task_score <= 100)",
            name="ck_cltrial_score_range",
        ),
        CheckConstraint(
            "(trial_status = 'valid' AND task_pass IS NOT NULL) OR "
            "(trial_status IN ('harness_failed', 'invalid_evidence') "
            "AND task_pass IS NULL)",
            name="ck_cltrial_pass_matches_status",
        ),
        CheckConstraint(
            "artifact_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_cltrial_artifact_sha256",
        ),
        Index("idx_cltrial_run", "run_id"),
        Index("idx_cltrial_case", "case_id"),
        Index("idx_cltrial_status", "trial_status"),
        Index("uq_cltrial_run_case_index", "run_id", "case_id", "trial_index", unique=True),
    )


class ChatloopEvalViolationRow(Base):
    __tablename__ = "chatloop_eval_violations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trial_id = Column(
        String(64),
        ForeignKey("chatloop_eval_trials.trial_id", ondelete="CASCADE"),
        nullable=False,
    )
    policy_id = Column(String(64), nullable=False)
    severity = Column(String(8), nullable=False)
    triggered_escalations = Column(JSONB, nullable=False, default=list)

    __table_args__ = (
        CheckConstraint(
            "severity IN ('C0', 'C1', 'C2', 'C3')",
            name="ck_clviolation_severity",
        ),
        Index("idx_clviolation_trial", "trial_id"),
        Index("idx_clviolation_policy", "policy_id"),
        Index("idx_clviolation_severity", "severity"),
        Index("uq_clviolation_trial_policy", "trial_id", "policy_id", unique=True),
    )


@dataclass(frozen=True, slots=True)
class TrialRecord:
    trial_id: str
    run_id: str
    case_id: str
    trial_index: int
    suite_type: str
    trial_status: str
    task_pass: bool | None
    task_score: float | None
    failure_reason: str | None
    artifact: ArtifactReference
    violations: tuple[Violation, ...] = ()

    def __post_init__(self) -> None:
        for field in ("trial_id", "run_id", "case_id"):
            if not isinstance(getattr(self, field), str) or not getattr(self, field):
                raise ValueError(f"{field} must be a non-empty string")
        if self.trial_status not in {"valid", "harness_failed", "invalid_evidence"}:
            raise ValueError(f"unknown trial_status: {self.trial_status}")
        if self.task_pass is not None and not isinstance(self.task_pass, bool):
            raise ValueError("task_pass must be a boolean or null")
        if self.trial_status == "valid" and self.task_pass is None:
            raise ValueError("valid trials require a boolean task_pass")
        if self.trial_status != "valid" and self.task_pass is not None:
            raise ValueError("invalid trials must preserve task_pass=null")
        if self.suite_type not in {"Capability", "Regression"}:
            raise ValueError(f"unknown suite_type: {self.suite_type}")
        if (
            isinstance(self.trial_index, bool)
            or not isinstance(self.trial_index, int)
            or self.trial_index < 0
        ):
            raise ValueError("trial_index must be a non-negative integer")
        if self.task_score is not None:
            if isinstance(self.task_score, bool) or not isinstance(self.task_score, (int, float)):
                raise ValueError("task_score must be a number or null")
            if not math.isfinite(self.task_score) or not 0.0 <= self.task_score <= 100.0:
                raise ValueError("task_score must be finite and between 0 and 100")
        if len(self.artifact.sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.artifact.sha256
        ):
            raise ValueError("artifact sha256 must be 64 lowercase hexadecimal characters")


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def prompt_sha() -> str:
    from app.chatloop.system_prompt import CHAT_SYSTEM_PROMPT

    return hashlib.sha256(CHAT_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


class ChatloopEvalRecorder:
    """两张专表的写入器 + 时间窗成本汇总。"""

    def __init__(self, session_factory: Any = None, *, initialize_schema: bool = True) -> None:
        self._sf = session_factory or SessionLocal
        # 幂等建表(无-alembic 模式)—— 仅本评估的两张表
        if initialize_schema:
            Base.metadata.create_all(
                bind=engine,
                tables=[
                    ChatloopEvalRunRow.__table__,
                    ChatloopEvalMetricRow.__table__,
                    ChatloopEvalTrialRow.__table__,
                    ChatloopEvalViolationRow.__table__,
                ],
                checkfirst=True,
            )

    def cost_tokens_since(self, start: datetime) -> tuple[float | None, int | None]:
        """best-effort:从 trace_spans 汇总 start 之后的 SUT LLM 成本/token(失败记 None)。"""
        try:
            with self._sf() as s:
                row = s.execute(
                    text(
                        "SELECT COALESCE(SUM((metadata->>'cost_cny')::float),0), "
                        # chat span 有 total_tokens;stream_step 只有 prompt+completion —— 两种都兼容
                        "COALESCE(SUM(COALESCE((metadata->>'total_tokens')::int, "
                        "(metadata->>'prompt_tokens')::int + (metadata->>'completion_tokens')::int, 0)),0) "
                        "FROM trace_spans WHERE started_at >= :start"
                    ),
                    {"start": start},
                ).one()
                return float(row[0]), int(row[1])
        except Exception:  # noqa: BLE001
            return None, None

    def record(self, run: dict[str, Any], metrics: list[dict[str, Any]]) -> str:
        run_id = run["run_id"]
        with self._sf() as s:
            s.add(ChatloopEvalRunRow(**run))
            for m in metrics:
                s.add(ChatloopEvalMetricRow(run_id=run_id, **m))
            s.commit()
        return run_id

    def record_trial(self, trial: TrialRecord) -> str:
        artifact = read_verified_artifact(trial.artifact)
        expected_identity = {
            "trial_id": trial.trial_id,
            "run_id": trial.run_id,
            "case_id": trial.case_id,
            "trial_index": trial.trial_index,
        }
        for field, expected in expected_identity.items():
            if artifact.get(field) != expected:
                raise ValueError(
                    f"artifact {field} does not match trial record: "
                    f"{artifact.get(field)!r} != {expected!r}"
                )
        with self._sf() as session:
            session.add(
                ChatloopEvalTrialRow(
                    trial_id=trial.trial_id,
                    run_id=trial.run_id,
                    case_id=trial.case_id,
                    trial_index=trial.trial_index,
                    suite_type=trial.suite_type,
                    trial_status=trial.trial_status,
                    task_pass=trial.task_pass,
                    task_score=trial.task_score,
                    failure_reason=trial.failure_reason,
                    artifact_path=str(Path(trial.artifact.path)),
                    artifact_sha256=trial.artifact.sha256,
                    created_at=now_iso(),
                )
            )
            for violation in trial.violations:
                session.add(
                    ChatloopEvalViolationRow(
                        trial_id=trial.trial_id,
                        policy_id=violation.policy_id,
                        severity=violation.severity,
                        triggered_escalations=list(violation.triggered_escalations),
                    )
                )
            session.commit()
        return trial.trial_id

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        duration_ms: int,
        cost_cny: float | None,
        total_tokens: int | None,
        config_patch: dict[str, Any] | None = None,
    ) -> None:
        """Finalize one previously recorded run without discarding start metadata."""
        with self._sf() as session:
            row = session.get(ChatloopEvalRunRow, run_id)
            if row is None:
                raise ValueError(f"unknown eval run: {run_id}")
            row.status = status
            row.duration_ms = duration_ms
            row.cost_cny = cost_cny
            row.total_tokens = total_tokens
            row.config_json = {**(row.config_json or {}), **(config_patch or {})}
            session.commit()


def new_run_id() -> str:
    return uuid4().hex[:16]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


__all__ = [
    "ChatloopEvalRunRow",
    "ChatloopEvalMetricRow",
    "ChatloopEvalTrialRow",
    "ChatloopEvalViolationRow",
    "ChatloopEvalRecorder",
    "TrialRecord",
    "git_sha",
    "prompt_sha",
    "new_run_id",
    "now_iso",
]
