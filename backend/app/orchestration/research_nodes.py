"""Outer-graph node functions for v0.5 research mode."""

from __future__ import annotations

from typing import Any

from app.agents.analyst import Analyst
from app.agents.data_collector import DataCollector
from app.agents.research_planner import ResearchPlanner
from app.agents.schemas import ResearchState
from app.agents.writer import Writer


async def research_planner_node(state: ResearchState, planner: ResearchPlanner) -> dict[str, Any]:
    sr = planner.step(state)
    return sr.state_update


async def data_collector_node(state: ResearchState, collector: DataCollector) -> dict[str, Any]:
    sr = await collector.collect_async(state)
    return sr.state_update


async def analyst_node(state: ResearchState, analyst: Analyst) -> dict[str, Any]:
    sr = analyst.step(state)
    return sr.state_update


async def writer_node(state: ResearchState, writer: Writer) -> dict[str, Any]:
    new_state = await writer.run(state)
    # Return the diff between old and new state so LangGraph merges correctly.
    # For alert_deep_dive mode, Writer populates portfolio_warning_report only;
    # deep_dive_section is reserved for future deep-dive text (e.g. EscalationCoordinator output).
    # For full_research mode, write to investment_report + report_markdown + chart_specs.
    if state.mode == "alert_deep_dive":
        return {
            "portfolio_warning_report": new_state.portfolio_warning_report,
            "deep_dive_section": new_state.deep_dive_section,
        }
    return {
        "investment_report": new_state.investment_report,
        "report_markdown": new_state.report_markdown,
        "chart_specs": new_state.chart_specs,
    }
