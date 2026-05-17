"""AblationVariant + PipelineFactory — V0/V1/V2/V3 swap."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from eval.dd_report.ablation.null_adapters import NullKBAdapter, SingleAgentPipeline
from eval.dd_report.ablation.variants import AblationVariant, build_pipeline_for_variant


def test_v0_baseline_uses_full_production_pipeline() -> None:
    """V0 baseline = 直接复用注入的 production_factory 不动."""
    prod_factory = MagicMock()
    adapter = build_pipeline_for_variant(
        AblationVariant.V0_BASELINE,
        production_factory=prod_factory,
    )
    assert adapter.pipeline_factory is prod_factory


def test_v1_no_rag_swaps_kb_adapter_to_null() -> None:
    """V1 无 RAG: KBBacktestAdapter 包一层, search 返 []."""
    prod_factory = MagicMock()
    adapter = build_pipeline_for_variant(
        AblationVariant.V1_NO_RAG,
        production_factory=prod_factory,
    )
    # adapter.pipeline_factory 不是原 prod_factory, 是 wrapper
    _ = adapter.pipeline_factory(
        tushare_adapter=MagicMock(),
        kb_adapter=MagicMock(),
        evaluator_client=MagicMock(),
    )
    # production_factory 被以 NullKBAdapter 注入调用
    _, kwargs = prod_factory.call_args
    assert isinstance(kwargs["kb_adapter"], NullKBAdapter)


def test_v2_no_multi_agent_swaps_pipeline_to_single_agent() -> None:
    """V2 单 agent: pipeline factory 整体替换成 SingleAgentPipeline."""
    prod_factory = MagicMock()
    build_pipeline_for_variant(
        AblationVariant.V2_NO_MULTI_AGENT,
        production_factory=prod_factory,
        single_agent_pipeline_class=SingleAgentPipeline,
    )
    # production_factory 完全不被使用
    prod_factory.assert_not_called()


def test_v3_no_critic_strips_critic_in_factory_kwargs() -> None:
    """V3 无 critic: 传 disable_critic=True 给 production_factory."""
    prod_factory = MagicMock()
    adapter = build_pipeline_for_variant(
        AblationVariant.V3_NO_CRITIC,
        production_factory=prod_factory,
    )
    # adapter.pipeline_factory 是 wrapper, 调用时把 disable_critic=True 透传
    wrapped_factory = adapter.pipeline_factory
    wrapped_factory(
        tushare_adapter=MagicMock(),
        kb_adapter=MagicMock(),
        evaluator_client=MagicMock(),
    )
    _, kwargs = prod_factory.call_args
    assert kwargs.get("disable_critic") is True


def test_unknown_variant_raises() -> None:
    with pytest.raises(ValueError, match="unknown ablation variant"):
        build_pipeline_for_variant("V99_INVALID", production_factory=MagicMock())


def test_null_kb_adapter_search_returns_empty() -> None:
    a = NullKBAdapter()
    assert a.search("anything", k=10) == []


def test_single_agent_pipeline_callable_returns_report() -> None:
    """SingleAgentPipeline 用单 prompt 一次性出报告 — 这里只验 protocol shape."""

    class _MockEvaluatorClient:
        model = "fake"

        def chat(self, prompt: str, response_format: Any = None) -> str:
            return "{}"  # SingleAgentPipeline 内部应有 fallback path

    pipe = SingleAgentPipeline(
        tushare_adapter=MagicMock(),
        kb_adapter=NullKBAdapter(),
        evaluator_client=_MockEvaluatorClient(),
    )
    assert callable(pipe)
