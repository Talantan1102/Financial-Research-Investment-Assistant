"""EvalResult + JudgeScores — Pydantic contracts for eval pipeline output.

`tool_correctness` may be None when the SUT doesn't expose tool calls (v0
SUT is bare LLMService). When None, the dimension is dropped from aggregate
scoring per spec § 8 (T3 threshold uses dim averages over present-only).

Stable v0~v3.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.schemas import ToolCall


class SUTOutput(BaseModel):
    """Output contract for any SUT (System Under Test) in the eval pipeline.

    Stable v0~v3 — Task 12 adds the SUT Protocol referencing this type.
    """

    model_config = ConfigDict(frozen=True)

    request_id: str
    response_text: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    escalate_offered: bool = False


class JudgeScores(BaseModel):
    model_config = ConfigDict(frozen=True)

    factuality: int = Field(ge=0, le=10)
    factuality_evidence: str
    tool_correctness: int | None = Field(default=None, ge=0, le=10)
    tool_correctness_evidence: str
    coverage: int = Field(ge=0, le=10)
    coverage_evidence: str
    structure: int = Field(ge=0, le=10)
    structure_evidence: str
    # v0.5 Task 12: additive — scored when report_markdown is provided to Judge.score
    report_markdown_quality: float | None = None

    @property
    def aggregate_avg(self) -> float:
        """Average over present (non-None) dimensions."""
        present = [
            v
            for v in (
                self.factuality,
                self.tool_correctness,
                self.coverage,
                self.structure,
                self.report_markdown_quality,
            )
            if v is not None
        ]
        return sum(present) / len(present)


class EvalResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    eval_id: str
    request_id: str
    case_id: str
    scores: JudgeScores
    judge_model: str
    judge_cost_cny: float = Field(ge=0.0)
    judge_latency_ms: int = Field(ge=0)
    timestamp: datetime

    # v1.x DD report eval 扩展字段(可选,保持 Plan C/c5 backward compat)
    # alembic 未引入(v0.9.x pattern); eval_recorder 走 CREATE TABLE IF NOT EXISTS 幂等
    backtest_run_id: str | None = Field(
        default=None, description="关联 backtest_runs.run_id (Phase 1 起)"
    )
    cut_off_date: str | None = Field(
        default=None, description="backtest 时点 ISO date string (YYYY-MM-DD)"
    )
    evaluator_llm: str | None = Field(
        default=None, description="评估时 swap 的 LLM model id (e.g. gpt-4o-2024-05-13)"
    )
    case_type: Literal["backtest", "sanity", "financebench", "cross_llm"] | None = Field(
        default=None, description="case 类别"
    )
    metric_scores_json: str | None = Field(
        default=None,
        description="BacktestMetricScores.model_dump_json() — Phase 2 backtest 5-metric scores",
    )


class BacktestRun(BaseModel):
    """Pydantic model paired with BacktestRunRow ORM.

    Mirrors the backtest_runs table schema. extra=forbid + frozen per repo convention.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    created_at: str  # ISO datetime string (matches legacy pattern)
    case_count: int = Field(ge=0)
    metric_summary_json: str | None = None
    status: str
    git_sha: str | None = None
    ablation_variant: str | None = None
    llm_model: str | None = None


GoldenCategory = Literal[
    "single_tool_call",
    "chat_multi_turn",
    "boundary_case",
]


class GoldenCase(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    category: GoldenCategory
    user_input: str
    expected_behavior: dict[str, Any]
    metadata: dict[str, Any]
    # v0.5 Task 12: additive — topic coverage hints for research-mode evaluation
    expected_topics: list[str] = Field(default_factory=list)


def load_golden_jsonl(path: Path) -> list[GoldenCase]:
    cases: list[GoldenCase] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            cases.append(GoldenCase.model_validate_json(line))
    return cases
