"""ResearchAgent — SUT-friendly wrapper for the research LangGraph.

Provides a ``run(user_input, request_id) -> SUTOutput`` interface consumed by
Task 12 EvalRunner and Task 13 cassette E2E tests.

Note on state deserialization:
    LangGraph 1.x returns the state as a plain dict after ainvoke.  Pydantic
    model fields may survive as instances (no JSON round-trip within a single
    ainvoke call) or come back as dicts depending on the LangGraph version and
    subgraph nesting.  Both paths are handled defensively below.
"""

from __future__ import annotations

from typing import Any

from app.agents.schemas import ResearchPlan, ResearchState, ToolCall
from app.services.eval_models import SUTOutput
from app.services.trace_service import TraceService


class ResearchAgent:
    """Thin wrapper that drives the compiled research graph with a SUT-compatible interface.

    Args:
        graph:         Compiled LangGraph object from :func:`build_research_graph`.
        trace_service: Optional TraceService for span persistence (future use).
    """

    def __init__(
        self,
        graph: Any,
        trace_service: TraceService | None = None,
    ) -> None:
        self._graph = graph
        self._trace = trace_service

    async def run(
        self,
        user_input: str,
        request_id: str,
        *,
        state_overrides: dict[str, Any] | None = None,
    ) -> SUTOutput:
        """Execute the research graph end-to-end and return a structured SUTOutput.

        Args:
            user_input:      The user's natural-language research query.
            request_id:      Unique identifier for this evaluation run; used as
                             LangGraph thread_id and propagated into ResearchState.
            state_overrides: Optional dict of ResearchState field overrides to
                             inject before graph invocation (E13 — chat-derived
                             signals from EscalationPacket).

        Returns:
            :class:`~app.services.eval_models.SUTOutput` with ``response_text``
            (the final report_markdown), ``tool_calls`` reverse-engineered from
            tool_results (for EvalRunner tool_correctness scoring), and
            ``request_id`` echo.
        """
        config = {"configurable": {"thread_id": f"research:eval:{request_id}"}}
        initial = ResearchState(
            user_id="eval",
            session_id=request_id,
            user_message=user_input,
            request_id=request_id,
        )
        if state_overrides:
            for k, v in state_overrides.items():
                if hasattr(initial, k):
                    setattr(initial, k, v)
        final: dict[str, Any] = await self._graph.ainvoke(initial.model_dump(), config=config)

        # plan may come back as dict or ResearchPlan instance
        plan_val = final.get("plan")
        if isinstance(plan_val, dict):
            plan_val = ResearchPlan.model_validate(plan_val)

        # Extract tool_calls from tool_results (reverse-engineer for EvalRunner scoring)
        tool_calls: list[ToolCall] = []
        for tr in final.get("tool_results") or []:
            tool_name = tr.tool_name if hasattr(tr, "tool_name") else tr["tool_name"]
            args = tr.args if hasattr(tr, "args") else tr["args"]
            tool_calls.append(ToolCall(tool_name=tool_name, args=args, rationale=""))

        return SUTOutput(
            request_id=request_id,
            response_text=final.get("report_markdown") or "",
            tool_calls=tool_calls,
        )
