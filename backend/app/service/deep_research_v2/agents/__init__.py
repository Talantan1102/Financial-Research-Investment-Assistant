
"""
DeepResearch V2.0 - Agents 模块

导出所有专家Agent
"""

from .architect import ChiefArchitect
from .base import AgentRegistry, BaseAgent
from .critic import CriticMaster
from .data_analyst import DataAnalyst
from .scout import DeepScout
from .wizard import CodeWizard
from .writer import LeadWriter

__all__ = [
    "BaseAgent",
    "AgentRegistry",
    "ChiefArchitect",
    "DeepScout",
    "CodeWizard",
    "CriticMaster",
    "LeadWriter",
    "DataAnalyst",
]
