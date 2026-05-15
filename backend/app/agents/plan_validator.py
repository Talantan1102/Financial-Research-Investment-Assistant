"""Plan validator — three-layer gate for LLM-generated ResearchPlan (v1.x A4).

L1 schema: Pydantic-strict via LLMService.schema=ResearchPlan (upstream).
L2 business rules: required dim coverage, tool palette whitelist, max_subtasks,
   max_tool_calls_per_subtask, per-subtask no duplicate tools.
L3 cost: optional, env-gated; not wired in v1.x ship.

forbid_duplicate_calls semantic: per-subtask only — cross-subtask reuse of
the same tool is allowed (e.g. get_news in 风险底线 + 近期催化 with
different analytical lens).

Coverage matching contract: a subtask covers a required dim iff the dim's
exact name string appears in the subtask's description or rationale.
LLM planner prompt MUST instruct the model to echo dim names verbatim
("财务全景 — ...", not paraphrased). This is asserted by
test_validate_paraphrased_dim_name_fails_coverage.

spec ref: docs/superpowers/specs/2026-05-15-v1.x-plan-template-validator-design.md § 4.3
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.agents.plan_template import DimensionSpec, PlanTemplate
from app.agents.schemas import ResearchPlan, Subtask

__all__ = ["ValidationResult", "validate_plan"]


class ValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool
    errors: list[str] = Field(default_factory=list)


def _dim_keyword_match(subtask: Subtask, dim_name: str) -> bool:
    """A subtask covers a dim if dim name appears in description or rationale."""
    return dim_name in subtask.description or dim_name in subtask.rationale


def _has_subtask_for_dim(plan: ResearchPlan, dim: DimensionSpec) -> bool:
    return any(_dim_keyword_match(s, dim["name"]) for s in plan.subtasks)


def _unique_candidate_tools_for_dim(plan: ResearchPlan, dim: DimensionSpec) -> int:
    candidates = set(dim["tool_candidates"])
    used: set[str] = set()
    for sub in plan.subtasks:
        if not _dim_keyword_match(sub, dim["name"]):
            continue
        for t in sub.required_tools:
            if t in candidates:
                used.add(t)
    return len(used)


def _subtask_duplicates(sub: Subtask) -> list[str]:
    """Return list of tool names that appear more than once in sub.required_tools.

    Empty list when no duplicates. Cross-subtask reuse is not detected here
    (per architectural decision — see module docstring)."""
    seen: set[str] = set()
    dups: set[str] = set()
    for t in sub.required_tools:
        if t in seen:
            dups.add(t)
        else:
            seen.add(t)
    return sorted(dups)


def validate_plan(plan: ResearchPlan, template: PlanTemplate) -> ValidationResult:
    errors: list[str] = []
    constraints = template["constraints"]
    palette = set(template["tool_palette"])

    # L2.a — required dims coverage + min_tools
    for dim in template["required_dimensions"]:
        if not _has_subtask_for_dim(plan, dim):
            errors.append(f"missing required dim: {dim['name']}")
            continue
        count = _unique_candidate_tools_for_dim(plan, dim)
        if count < dim["min_tools"]:
            errors.append(
                f"dim '{dim['name']}' has < {dim['min_tools']} tools "
                f"(got {count} from candidates {dim['tool_candidates']})"
            )

    # L2.b — tool palette whitelist
    for sub in plan.subtasks:
        for t in sub.required_tools:
            if t not in palette:
                errors.append(f"tool '{t}' not in palette (LLM hallucinated)")

    # L2.c — max_subtasks
    max_subs = constraints["max_subtasks"]
    if len(plan.subtasks) > max_subs:
        errors.append(f"too many subtasks: {len(plan.subtasks)} > {max_subs}")

    # L2.d — per-subtask tool count
    max_per = constraints["max_tool_calls_per_subtask"]
    for sub in plan.subtasks:
        if len(sub.required_tools) > max_per:
            errors.append(
                f"subtask '{sub.subtask_id}' has {len(sub.required_tools)} tools > {max_per}"
            )

    # L2.e — per-subtask no duplicates (cross-subtask reuse is OK)
    if constraints["forbid_duplicate_calls"]:
        for sub in plan.subtasks:
            dups = _subtask_duplicates(sub)
            if dups:
                errors.append(
                    f"subtask '{sub.subtask_id}' has duplicate tool(s) "
                    f"{dups} in required_tools={sub.required_tools}"
                )

    # L3 cost — not wired in v1.x

    return ValidationResult(ok=not errors, errors=errors)
