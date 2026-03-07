# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""Skill 基类 - MCP Server 工具抽象基类

参考 ToolExecutor 设计，提供统一的工具注册、发现和执行接口。
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Callable, Optional, Type
from dataclasses import dataclass, field
from pydantic import BaseModel, Field
import asyncio
import traceback
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


@dataclass
class ToolParameter:
    """工具参数定义"""
    name: str
    type: str  # string, number, integer, boolean, array, object
    description: str
    required: bool = True
    default: Any = None
    enum: Optional[List[Any]] = None


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str
    parameters: List[ToolParameter]
    
    def to_json_schema(self) -> Dict[str, Any]:
        """转换为 JSON Schema 格式"""
        properties = {}
        required = []
        
        for param in self.parameters:
            prop = {
                "type": param.type,
                "description": param.description
            }
            if param.enum:
                prop["enum"] = param.enum
            if param.default is not None:
                prop["default"] = param.default
            
            properties[param.name] = prop
            
            if param.required:
                required.append(param.name)
        
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required
            }
        }


@dataclass
class ToolResult:
    """工具执行结果"""
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error
        }


class BaseSkill(ABC):
    """
    Skill 基类
    
    所有 MCP Skill 必须继承此类，实现 _register_tools 方法注册工具。
    
    示例：
        class MySkill(BaseSkill):
            name = "my_skill"
            description = "My skill description"
            
            def _register_tools(self):
                self.register_tool(
                    name="my_tool",
                    handler=self.my_tool_handler,
                    description="Tool description",
                    parameters=[
                        ToolParameter(name="param1", type="string", description="Param1 description")
                    ]
                )
    """
    
    name: str = ""
    description: str = ""
    
    def __init__(self, name: str = None, description: str = None):
        self.name = name or self.__class__.name or self.__class__.__name__
        self.description = description or self.__class__.description or ""
        self._tools: Dict[str, Callable] = {}
        self._tool_definitions: Dict[str, ToolDefinition] = {}
        self._logger = logging.getLogger(self.name)
        self._initialized = False
        self._register_tools()
    
    @abstractmethod
    def _register_tools(self):
        """
        注册工具，子类必须实现
        
        在此方法中调用 self.register_tool() 注册该 Skill 提供的所有工具。
        """
        pass
    
    def register_tool(
        self, 
        name: str, 
        handler: Callable, 
        description: str, 
        parameters: List[ToolParameter]
    ):
        """
        注册工具
        
        Args:
            name: 工具名称（唯一标识）
            handler: 工具处理函数（同步或异步）
            description: 工具描述
            parameters: 参数定义列表
        """
        if name in self._tools:
            self._logger.warning(f"工具 '{name}' 已存在，将被覆盖")
        
        self._tools[name] = handler
        self._tool_definitions[name] = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters
        )
        self._logger.info(f"已注册工具: {name}")
    
    def discover_tools(self) -> List[ToolDefinition]:
        """
        发现所有可用的工具
        
        Returns:
            工具定义列表
        """
        return list(self._tool_definitions.values())
    
    def discover_tools_json(self) -> List[Dict[str, Any]]:
        """
        发现所有可用的工具（JSON Schema 格式）
        
        Returns:
            工具定义列表（JSON Schema）
        """
        return [tool.to_json_schema() for tool in self.discover_tools()]
    
    async def execute_tool(self, tool_name: str, params: Dict[str, Any]) -> ToolResult:
        """
        执行指定工具
        
        Args:
            tool_name: 工具名称
            params: 工具参数
        
        Returns:
            ToolResult 执行结果
        """
        if tool_name not in self._tools:
            return ToolResult(
                success=False,
                error=f"工具 '{tool_name}' 不存在于 Skill '{self.name}'"
            )
        
        handler = self._tools[tool_name]
        tool_def = self._tool_definitions[tool_name]
        
        # 参数校验
        validation_error = self._validate_params(params, tool_def)
        if validation_error:
            return ToolResult(success=False, error=validation_error)
        
        try:
            # 执行工具（支持同步和异步）
            if asyncio.iscoroutinefunction(handler):
                result = await handler(**params)
            else:
                result = handler(**params)
            
            # 标准化返回结果
            if isinstance(result, ToolResult):
                return result
            elif isinstance(result, dict):
                success = result.get("success", True)
                data = result.get("data") if success else None
                error = result.get("error") if not success else None
                return ToolResult(success=success, data=data, error=error)
            else:
                return ToolResult(success=True, data=result)
                
        except Exception as e:
            self._logger.error(f"工具 '{tool_name}' 执行失败: {e}")
            self._logger.debug(traceback.format_exc())
            return ToolResult(
                success=False,
                error=f"工具执行失败: {str(e)}"
            )
    
    def _validate_params(self, params: Dict[str, Any], tool_def: ToolDefinition) -> Optional[str]:
        """
        参数校验
        
        Args:
            params: 传入的参数
            tool_def: 工具定义
        
        Returns:
            错误信息，校验通过返回 None
        """
        # 检查必填参数
        for param in tool_def.parameters:
            if param.required and param.name not in params:
                return f"缺少必填参数: {param.name}"
        
        # 类型检查（简化版，可扩展）
        for param_name, value in params.items():
            param_def = next((p for p in tool_def.parameters if p.name == param_name), None)
            if not param_def:
                continue  # 允许额外参数
            
            type_map = {
                "string": str,
                "number": (int, float),
                "integer": int,
                "boolean": bool,
                "array": list,
                "object": dict
            }
            
            expected_type = type_map.get(param_def.type)
            if expected_type and not isinstance(value, expected_type):
                return f"参数 '{param_name}' 类型错误，期望 {param_def.type}"
        
        return None
    
    def get_tool_handler(self, tool_name: str) -> Optional[Callable]:
        """
        获取工具处理器
        
        Args:
            tool_name: 工具名称
        
        Returns:
            工具处理器函数，不存在返回 None
        """
        return self._tools.get(tool_name)
    
    def has_tool(self, tool_name: str) -> bool:
        """
        检查是否包含指定工具
        
        Args:
            tool_name: 工具名称
        
        Returns:
            是否存在
        """
        return tool_name in self._tools
    
    @property
    def tool_count(self) -> int:
        """工具数量"""
        return len(self._tools)


# 向后兼容别名
Skill = BaseSkill


def tool(name: str = None, description: str = "", timeout: int = 30):
    """
    工具装饰器，用于注册工具
    
    示例：
        @tool(name="get_quote", description="获取股票行情")
        async def get_quote(self, symbol: str):
            ...
    
    Args:
        name: 工具名称（默认使用函数名）
        description: 工具描述
        timeout: 超时时间（秒）
    
    Returns:
        装饰器函数
    """
    def decorator(func):
        # 在Skill类中使用时，通过元数据标记
        func._tool_name = name or func.__name__
        func._tool_description = description
        func._tool_timeout = timeout
        return func
    return decorator
