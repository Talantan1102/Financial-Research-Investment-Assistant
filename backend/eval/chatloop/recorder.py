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
import subprocess
from datetime import datetime
from typing import Any
from uuid import uuid4

from app.core.database import Base, SessionLocal, engine
from sqlalchemy import Column, Float, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB


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

    def __init__(self, session_factory: Any = None) -> None:
        self._sf = session_factory or SessionLocal
        # 幂等建表(无-alembic 模式)—— 仅本评估的两张表
        Base.metadata.create_all(
            bind=engine,
            tables=[ChatloopEvalRunRow.__table__, ChatloopEvalMetricRow.__table__],
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


def new_run_id() -> str:
    return uuid4().hex[:16]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


__all__ = [
    "ChatloopEvalRunRow",
    "ChatloopEvalMetricRow",
    "ChatloopEvalRecorder",
    "git_sha",
    "prompt_sha",
    "new_run_id",
    "now_iso",
]
