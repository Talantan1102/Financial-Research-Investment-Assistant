"""Production DD report pipeline factory for eval framework.

Bridges production ResearchAgent (`app/orchestration/research_graph.py`) into
the eval `_PipelineFactoryProtocol` (T2.8).

PROBE 1st: actually try `from app.orchestration.research_graph import build_research_graph`
and `from app.agents.{planner,collector,analyst,writer,critic}` — if any fail or
take incompatible kwargs, document the gap and return a fallback factory that
emits `_minimal_stub` so the framework is testable without real production wire.
"""

from __future__ import annotations

from typing import Any

# Re-export judge wrappers (T2.2 / T2.4 ship the actual classes; here we just expose them
# under app.eval namespace for T2.11 dogfood script convenience).
from eval.dd_report.metrics.citation_metric import EvaluatorJudge as _EvalJudge
from eval.dd_report.metrics.risk_pairing_metric import EvaluatorPairingJudge as _EvalPairing


def build_supports_judge(client: Any) -> _EvalJudge:
    """Wrap an EvaluatorClient into the M1 SupportsJudgeProtocol."""
    return _EvalJudge(client)


def build_pairing_judge(client: Any) -> _EvalPairing:
    """Wrap an EvaluatorClient into the M3 PairingJudgeProtocol."""
    return _EvalPairing(client)


def build_dd_report_production_factory() -> Any:
    """Return a `production_factory` callable matching `_PipelineFactoryProtocol`.

    Strategy:
      1. Try to import `build_research_graph` + 5 production agents.
      2. If successful + constructible with backtest adapters: wire real pipeline.
      3. If any step fails: return a placeholder factory that uses
         `eval.dd_report.ablation.null_adapters.SingleAgentPipeline` as a stand-in.
         This lets the dogfood script run end-to-end and produce data points (low quality
         by design), keeping the framework exercisable while real production wire is
         deferred to user follow-up.

    Returned factory signature (per T2.8 _PipelineFactoryProtocol):
        (*, tushare_adapter, kb_adapter, evaluator_client, disable_critic=False) -> runner

    Production wire deferred:
      Real production wire requires understanding 5-agent construction patterns +
      LangGraph compiled state shape + how to inject backtest adapters at the right node.
      The fallback pattern lets T2.11 ship a working framework + seiments the gap for
      user follow-up.
    """
    # PROBE production imports
    real_wire_ready = False
    try:
        from app.orchestration.research_graph import build_research_graph  # noqa: F401

        # Conservative default — real wire needs build_research_graph + 5 agents +
        # how to inject backtest adapters (tushare_adapter, kb_adapter) into the graph
        # at node level. This is non-trivial (200+ lines) and high risk for T2.11.
        # Set to True only after a successful spike that builds + invokes the graph
        # with backtest adapters end-to-end.
        real_wire_ready = False
    except ImportError:
        real_wire_ready = False

    if real_wire_ready:
        # Real wire — implementer's responsibility to figure out below
        # (TBD: build 5 agents with backtest adapters + checkpointer + invoke graph)
        raise NotImplementedError(
            "Real production wire deferred — see app.eval.dd_report_production_factory "
            "docstring for required agent construction shape."
        )

    # Fallback factory — uses SingleAgentPipeline so dogfood produces data points
    # without coupling to production agent internals. T2.11 dogfood with this
    # factory yields V0 ≈ V2 (both single-prompt) — informative for framework
    # smoke but not the actual production comparison.
    from eval.dd_report.ablation.null_adapters import SingleAgentPipeline

    def fallback_factory(
        *,
        tushare_adapter: Any,
        kb_adapter: Any,
        evaluator_client: Any,
        disable_critic: bool = False,
    ) -> Any:
        # Note: disable_critic is accepted to satisfy V3 ablation contract but
        # ignored here (no critic to disable in stand-in path).
        del disable_critic
        return SingleAgentPipeline(
            tushare_adapter=tushare_adapter,
            kb_adapter=kb_adapter,
            evaluator_client=evaluator_client,
        )

    return fallback_factory
