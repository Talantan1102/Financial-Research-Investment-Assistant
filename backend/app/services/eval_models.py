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

    @property
    def aggregate_avg(self) -> float:
        """Average over present (non-None) dimensions."""
        present = [
            v
            for v in (self.factuality, self.tool_correctness, self.coverage, self.structure)
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


def load_golden_jsonl(path: Path) -> list[GoldenCase]:
    cases: list[GoldenCase] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            cases.append(GoldenCase.model_validate_json(line))
    return cases
