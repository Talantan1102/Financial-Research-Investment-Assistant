"""ChatAgent — SUT-friendly wrapper around the compiled LangGraph chat graph.

Provides a ``run(user_input, request_id) -> SUTOutput`` interface consumed by
Task 12 EvalRunner and Task 13 cassette E2E tests.

Note on `plan` deserialization:
    LangGraph 1.x returns the state as a plain dict.  When the graph nodes
    return a ``Plan`` instance in their state-update dict, LangGraph preserves
    it as a ``Plan`` instance (not re-serialised to dict) because no JSON
    round-trip occurs within a single ainvoke call.  Confirmed by Task 10
    spike: ``final.get("plan")`` is a ``Plan`` instance.  If that changes in
    a future LangGraph version, ``Plan.model_validate(plan_val)`` handles the
    dict-fallback path.
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from app.agents.schemas import Plan
from app.services.eval_models import SUTOutput
from app.services.trace_service import TraceService


class ChatAgent:
    """Thin wrapper that drives the compiled chat graph with a SUT-compatible interface.

    Args:
        graph:         Compiled LangGraph StateGraph from :func:`build_chat_graph`.
        trace_service: Optional TraceService for span persistence (future use).
    """

    def __init__(
        self,
        graph: CompiledStateGraph[Any, Any, Any, Any],
        trace_service: TraceService | None = None,
    ) -> None:
        self._graph = graph
        self._trace = trace_service

    async def run(self, user_input: str, request_id: str) -> SUTOutput:
        """Execute the chat graph end-to-end and return a structured SUTOutput.

        Args:
            user_input: The user's natural-language query.
            request_id: Unique identifier for this evaluation run; used as
                        LangGraph thread_id and propagated into GraphState.

        Returns:
            :class:`~app.services.eval_models.SUTOutput` with ``response_text``,
            ``tool_calls`` extracted from the final planner plan, and
            ``request_id`` echo.
        """
        from app.agents.schemas import GraphState

        config: RunnableConfig = {"configurable": {"thread_id": f"eval:{request_id}"}}
        initial = GraphState(
            user_id="eval",
            session_id=request_id,
            user_message=user_input,
            request_id=request_id,
        )
        final: dict[str, Any] = await self._graph.ainvoke(initial.model_dump(), config=config)

        # plan is a Plan instance in LangGraph 1.x (no JSON round-trip within ainvoke).
        # Guard against potential dict form in future versions.
        plan_val = final.get("plan")
        plan: Plan | None
        if plan_val is None:
            plan = None
        elif isinstance(plan_val, Plan):
            plan = plan_val
        else:
            # Defensive: deserialise from dict if LangGraph ever serialises the state.
            plan = Plan.model_validate(plan_val)

        return SUTOutput(
            request_id=request_id,
            response_text=final.get("final_response") or "",
            tool_calls=plan.tool_calls if plan else [],
        )
