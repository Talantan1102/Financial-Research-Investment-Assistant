"""Legacy module — see backend/LEGACY_LAYOUT.md for module-by-module status and v1.x evolution plan.

New features should prefer importing from `app/services/*` (plural, v0.8.x main path).
"""
# Config module

from .llm_config import (
    AgentModelConfig,
    AgentsConfig,
    LLMConfig,
    ResearchConfig,
    get_agent_model,
    get_config,
    get_default_model,
    print_config,
    reload_config,
)

__all__ = [
    "LLMConfig",
    "AgentModelConfig",
    "AgentsConfig",
    "ResearchConfig",
    "get_config",
    "reload_config",
    "get_agent_model",
    "get_default_model",
    "print_config",
]
