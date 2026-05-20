"""AblationVariant 枚举 + build_pipeline_for_variant (spec § 4.7)."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Any

from eval.dd_report.ablation.null_adapters import (
    NullKBAdapter,
    SingleAgentPipeline,
)
from eval.dd_report.pipeline_adapter import DDReportPipelineAdapter


class AblationVariant(StrEnum):
    V0_BASELINE = "V0_baseline"
    V1_NO_RAG = "V1_no_rag"
    V2_NO_MULTI_AGENT = "V2_no_multi_agent"
    V3_NO_CRITIC = "V3_no_critic"


def build_pipeline_for_variant(
    variant: AblationVariant | str,
    *,
    production_factory: Callable[..., Any],
    single_agent_pipeline_class: type = SingleAgentPipeline,
) -> DDReportPipelineAdapter:
    """根据 variant 装配 PipelineAdapter."""
    if variant == AblationVariant.V0_BASELINE:
        return DDReportPipelineAdapter(pipeline_factory=production_factory)

    if variant == AblationVariant.V1_NO_RAG:

        def factory_v1(*, tushare_adapter: Any, kb_adapter: Any, evaluator_client: Any) -> Any:
            return production_factory(
                tushare_adapter=tushare_adapter,
                kb_adapter=NullKBAdapter(),
                evaluator_client=evaluator_client,
            )

        return DDReportPipelineAdapter(pipeline_factory=factory_v1)

    if variant == AblationVariant.V2_NO_MULTI_AGENT:

        def factory_v2(*, tushare_adapter: Any, kb_adapter: Any, evaluator_client: Any) -> Any:
            return single_agent_pipeline_class(
                tushare_adapter=tushare_adapter,
                kb_adapter=kb_adapter,
                evaluator_client=evaluator_client,
            )

        return DDReportPipelineAdapter(pipeline_factory=factory_v2)

    if variant == AblationVariant.V3_NO_CRITIC:

        def factory_v3(*, tushare_adapter: Any, kb_adapter: Any, evaluator_client: Any) -> Any:
            return production_factory(
                tushare_adapter=tushare_adapter,
                kb_adapter=kb_adapter,
                evaluator_client=evaluator_client,
                disable_critic=True,
            )

        return DDReportPipelineAdapter(pipeline_factory=factory_v3)

    raise ValueError(f"unknown ablation variant: {variant!r}")
