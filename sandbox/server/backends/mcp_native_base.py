"""
MCP Native Backend Base Class - 金融研投助手模式

Backend 直接作为 MCP Server，暴露金融研投助手风格的 3 个工具：
- select_skill(skill_name, reason)
- get_skill_tools(name)
- execute_skill_tool(skill_name, tool_name, arguments)

与金融研投助手 MCP Server 保持完全一致。
"""

import logging
import asyncio
from abc import abstractmethod
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from dataclasses import dataclass, field

if TYPE_CHECKING:
    from ..app import HTTPServiceServer

logger = logging.getLogger("MCPNativeBackend")


@dataclass
class MCPBackendConfig:
    """MCP Backend 配置"""
    enabled: bool = True
    default_config: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class MCPNativeBackend:
    """
    MCP Native Backend 基类 - 金融研投助手模式
    
    Backend 直接作为 MCP Server，暴露 3 个工具：
    - select_skill(skill_name, reason) -> 选择合适的 Skill
    - get_skill_tools(name) -> 获取 Skill 的工具列表
    - execute_skill_tool(skill_name, tool_name, arguments) -> 执行具体工具
    """
    
    name: str = "mcp_native"
    description: str = "MCP Native Backend (金融研投助手模式)"
    version: str = "2.0.0"
    
    def __init__(self, config: Optional[MCPBackendConfig] = None):
        self.config = config or MCPBackendConfig()
        self._server: Optional["HTTPServiceServer"] = None
    
    # ========================================================================
    # 生命周期方法（由 Server 调用）
    # ========================================================================
    
    async def warmup(self):
        """
        Warmup - 初始化全局资源
        
        子类应重写此方法进行初始化：
        - 加载 Skills
        - 初始化连接池
        """
        pass
    
    async def shutdown(self):
        """
        Shutdown - 释放全局资源
        
        子类应重写此方法进行清理：
        - 关闭连接池
        - 卸载模型
        """
        pass
    
    # ========================================================================
    # 金融研投助手模式方法（必须由子类实现）
    # ========================================================================
    
    @abstractmethod
    async def select_skill(self, skill_name: str, reason: str) -> Dict[str, Any]:
        """
        Round 1: 根据用户问题选择合适的 Skill
        
        Args:
            skill_name: Skill 名称
            reason: 选择理由
            
        Returns:
            选择结果，格式: {"success": True/False, "skill_name": "...", ...}
        """
        raise NotImplementedError()
    
    @abstractmethod
    async def get_skill_tools(self, name: str) -> Dict[str, Any]:
        """
        Round 2: 获取指定 Skill 的所有可用工具列表
        
        Args:
            name: Skill 名称
            
        Returns:
            工具列表，格式: {"success": True/False, "tools": [...], ...}
        """
        raise NotImplementedError()
    
    @abstractmethod
    async def execute_skill_tool(self, skill_name: str, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Round 3: 执行指定 Skill 的具体工具
        
        Args:
            skill_name: Skill 名称
            tool_name: 工具名称（不含 skill 前缀）
            arguments: 工具参数
            
        Returns:
            工具执行结果，格式: {"success": True/False, "data": {...}, ...}
        """
        raise NotImplementedError()
    
    # ========================================================================
    # Server 管理（由 Server 调用）
    # ========================================================================
    
    def _set_server(self, server: "HTTPServiceServer"):
        """设置 Server 实例（由 Server 调用）"""
        self._server = server
    
    def get_server(self) -> Optional["HTTPServiceServer"]:
        """获取 Server 实例"""
        return self._server
    
    # ========================================================================
    # 辅助方法
    # ========================================================================
    
    def get_all_skills(self) -> Dict[str, Dict[str, str]]:
        """
        获取所有可用的 Skills 信息
        
        子类可以重写此方法返回自定义的 Skills 列表。
        
        Returns:
            {skill_name: {"description": "...", "use_when": "..."}}
        """
        # 默认返回空字典，子类应重写
        return {}


# 向后兼容的别名
MCPResource = None  # 已弃用
MCPTool = None  # 已弃用
