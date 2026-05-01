"""Agent ABC — all agents are stateless typed actors.

DispatchSubAgent interface lives here as a placeholder per
project_agents_layer.md memory: v0 doesn't dispatch sub-agents (no use
case), but the interface is reserved so v0.5 Critic can implement
multi-dimension parallel scoring without changing the base class.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.agents.schemas import GraphState, StepResult
from app.services.llm_response import Tier
from app.services.llm_service import LLMService


class Agent(ABC):
    """Stateless typed actor with strict Pydantic I/O.

    Subclasses must:
    - Set class attribute `name: str` (used for trace span names)
    - Set class attribute `model_tier: Tier` ("fast"|"balanced"|"deep")
    - Implement `step(state) -> StepResult`
    """

    name: str
    model_tier: Tier

    def __init__(self, llm: LLMService) -> None:
        self._llm = llm

    @abstractmethod
    def step(self, state: GraphState) -> StepResult:
        """Run one step: read graph state, optionally call LLM/tools, return state_update."""

    def dispatch_subagent(self, name: str, state: GraphState) -> StepResult:
        """Placeholder for v0.5 sub-agent dispatch.

        v0 does not have multi-dimension parallel scoring (Critic), so this
        method always raises. v0.5 Critic will override or this base method
        will gain a real implementation tied to a SubAgentRegistry.
        """
        raise NotImplementedError(
            f"DispatchSubAgent ({name!r}) is reserved for v0.5+; v0 has no use case."
        )
