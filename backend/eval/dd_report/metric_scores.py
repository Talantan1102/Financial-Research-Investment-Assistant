"""BacktestMetricScores — Phase 2 per-case score schema(去推荐后 4 metric).

spec § 4.2 / § 5.2

不复用 app.services.eval_models.JudgeScores —— 后者字段是
factuality / coverage / structure / tool_correctness / report_markdown_quality
(单 judge 4-5 维 rubric), 而 Phase 2 5 metric 是 backtest 维度的另一套体系。
两套 schema 并存: 普通 eval(chat path)用 JudgeScores, backtest 用本 schema。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BacktestMetricScores(BaseModel):
    """4 metric per-case scores. 序列化到 eval_results.metric_scores_json 列."""

    model_config = ConfigDict(extra="ignore")

    # M1 Citation precision/recall (spec § 4.2)
    m1_citation_precision: float = Field(ge=0.0, le=1.0)
    m1_citation_recall: float = Field(ge=0.0, le=1.0)

    # M2 Numerical accuracy (spec § 4.2)
    m2_numerical_accuracy: float = Field(ge=0.0, le=1.0)
    m2_numerical_total: int = Field(ge=0)
    m2_numerical_correct: int = Field(ge=0)

    # M3 Risk-mitigation pairing (spec § 4.2)
    m3_risk_pairing_score: float = Field(ge=0.0, le=1.0)

    # 去推荐改造(2026-06-04):预测回测(原 M4 方向/目标价命中/风险预警)整把尺子下线。

    # M5 Multi-LLM consensus (spec § 4.3)
    m5_composite_mean: float = Field(ge=0.0, le=10.0)
    m5_composite_majority: float = Field(ge=0.0, le=10.0)
    m5_composite_disagreement_max: float = Field(ge=0.0)

    # 详情(失败 cite list / wrong numeric / mitigation 评语 / 各 judge raw)
    details_json: dict[str, Any] = Field(default_factory=dict)
