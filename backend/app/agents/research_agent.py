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

from collections.abc import AsyncIterator
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
            # C58: use model_validate for revalidating reconstruction so that
            # Pydantic field constraints (e.g. planner_retry_count le=2) are
            # enforced.  setattr / model_copy(update=...) both bypass validators.
            valid_overrides = {k: v for k, v in state_overrides.items() if hasattr(initial, k)}
            initial = ResearchState.model_validate({**initial.model_dump(), **valid_overrides})
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

    async def run_streaming(
        self,
        user_input: str,
        request_id: str,
        *,
        state_overrides: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream graph events as ``{event, data}`` dicts.

        Yields intermediate SSE-ready dicts for each significant graph event
        (node completions, tool start/end).  The final item is always::

            {"event": "_final_sut_output", "data": SUTOutput}

        This allows callers to relay progress events while still obtaining the
        final structured output, without a second ``ainvoke`` round-trip.

        Node name mapping (actual graph node names → SSE event names):
            - ``research_planner_node``  → ``research_planner_done``
            - ``data_collector_node``    → (no event — internal detail)
            - ``analyst_node``           → ``research_analyst_done``
            - ``writer_node``            → ``research_writer_done``
            - ``critic_node`` / any name containing "critic" → ``research_critic_done``
            - ``LangGraph`` (top-level)  → used to capture final state

        Args:
            user_input:      The user's natural-language research query.
            request_id:      Unique identifier; used as LangGraph thread_id.
            state_overrides: Optional ResearchState field overrides (E13).

        Yields:
            Dicts with ``event`` (str) and ``data`` (dict or SUTOutput).
        """
        config = {"configurable": {"thread_id": f"research:{request_id}"}}
        initial = ResearchState(
            user_id="eval",
            session_id=request_id,
            user_message=user_input,
            request_id=request_id,
        )
        if state_overrides:
            # C58: revalidating reconstruction (mirrors run() above)
            valid_overrides = {k: v for k, v in state_overrides.items() if hasattr(initial, k)}
            initial = ResearchState.model_validate({**initial.model_dump(), **valid_overrides})

        final_state: dict[str, Any] = {}
        async for chunk in self._graph.astream_events(
            initial.model_dump(), config=config, version="v2"
        ):
            kind = chunk.get("event", "")
            name = chunk.get("name", "")
            if kind == "on_chain_end":
                # Map actual node names to SSE event names
                if name in ("research_planner_node", "planner", "research_planner"):
                    yield {"event": "research_planner_done", "data": {"name": name}}
                elif name in ("analyst_node", "analyst", "research_analyst"):
                    yield {"event": "research_analyst_done", "data": {"name": name}}
                elif name in ("writer_node", "writer", "research_writer"):
                    yield {"event": "research_writer_done", "data": {"name": name}}
                elif "critic" in name.lower():
                    yield {"event": "research_critic_done", "data": {"name": name}}
                elif name == "LangGraph":
                    final_state = (chunk.get("data") or {}).get("output", {}) or {}
            elif kind == "on_tool_start":
                yield {"event": "research_tool_start", "data": {"tool": name}}
            elif kind == "on_tool_end":
                yield {"event": "research_tool_end", "data": {"tool": name}}

        response_text = (
            final_state.get("report_markdown") or final_state.get("final_response") or ""
        )
        yield {
            "event": "_final_sut_output",
            "data": SUTOutput(
                request_id=request_id,
                response_text=response_text,
                tool_calls=[],
            ),
        }
