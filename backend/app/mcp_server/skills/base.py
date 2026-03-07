"""
MCP Skill 基类模块

提供所有Financial Skills的统一接口规范
"""

import asyncio
import traceback
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Type, get_type_hints
from dataclasses import dataclass, field
from functools import wraps
import inspect
import time


@dataclass
class ToolParameter:
    """工具参数定义"""
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None
    enum: Optional[List[str]] = None


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str
    parameters: List[ToolParameter]
    func: Callable
    return_type: str = "any"
    timeout: int = 30  # 默认超时30秒


@dataclass
class ToolResult:
    """工具执行结果"""
    success: bool
    data: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "execution_time_ms": self.execution_time_ms
        }


class SkillError(Exception):
    """Skill基础异常"""
    def __init__(self, message: str, code: str = "SKILL_ERROR"):
        self.message = message
        self.code = code
        super().__init__(self.message)


class ToolExecutionError(SkillError):
    """工具执行异常"""
    def __init__(self, message: str, tool_name: str = ""):
        super().__init__(message, code="TOOL_EXECUTION_ERROR")
        self.tool_name = tool_name


class ToolNotFoundError(SkillError):
    """工具未找到异常"""
    def __init__(self, tool_name: str):
        super().__init__(f"Tool '{tool_name}' not found", code="TOOL_NOT_FOUND")
        self.tool_name = tool_name


class ToolTimeoutError(SkillError):
    """工具执行超时异常"""
    def __init__(self, tool_name: str, timeout: int):
        super().__init__(
            f"Tool '{tool_name}' execution timeout after {timeout}s",
            code="TOOL_TIMEOUT"
        )
        self.tool_name = tool_name
        self.timeout = timeout


class ToolValidationError(SkillError):
    """工具参数验证异常"""
    def __init__(self, message: str, param_name: str = ""):
        super().__init__(message, code="TOOL_VALIDATION_ERROR")
        self.param_name = param_name


def tool(
    name: Optional[str] = None,
    description: Optional[str] = None,
    timeout: int = 30
):
    """
    工具装饰器，用于标记类方法为MCP工具
    
    使用示例：
        class MySkill(Skill):
            @tool(name="get_stock", description="获取股票行情")
            async def get_stock(self, symbol: str) -> dict:
                return {"price": 100}
    """
    def decorator(func: Callable) -> Callable:
        # 设置工具元数据
        func._is_tool = True
        func._tool_name = name or func.__name__
        func._tool_description = description or func.__doc__ or ""
        func._tool_timeout = timeout
        
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await func(*args, **kwargs)
        
        # 复制元数据
        wrapper._is_tool = True
        wrapper._tool_name = func._tool_name
        wrapper._tool_description = func._tool_description
        wrapper._tool_timeout = func._tool_timeout
        
        return wrapper
    return decorator


class Skill(ABC):
    """
    MCP Skill 抽象基类
    
    所有Financial Skills都必须继承此类
    """
    
    def __init__(self, name: str, description: str = ""):
        """
        初始化Skill
        
        Args:
            name: Skill名称
            description: Skill描述
        """
        self.name = name
        self.description = description
        self._tools: Dict[str, ToolDefinition] = {}
        self._initialized = False
        
        # 自动发现并注册工具
        self._discover_tools()
    
    def _discover_tools(self) -> None:
        """
        自动发现类中标记为工具的方法
        """
        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            if callable(attr) and hasattr(attr, '_is_tool'):
                self._register_tool_from_method(attr)
    
    def _register_tool_from_method(self, method: Callable) -> None:
        """
        从方法注册工具
        
        Args:
            method: 标记为工具的方法
        """
        tool_name = getattr(method, '_tool_name', method.__name__)
        tool_description = getattr(method, '_tool_description', method.__doc__ or "")
        tool_timeout = getattr(method, '_tool_timeout', 30)
        
        # 解析参数
        sig = inspect.signature(method)
        type_hints = get_type_hints(method)
        
        parameters = []
        for param_name, param in sig.parameters.items():
            # 跳过self参数
            if param_name == 'self':
                continue
            
            # 获取参数类型
            param_type = type_hints.get(param_name, str)
            type_str = self._python_type_to_json_type(param_type)
            
            # 判断是否为必填参数
            is_required = param.default is inspect.Parameter.empty
            default_value = None if is_required else param.default
            
            parameters.append(ToolParameter(
                name=param_name,
                type=type_str,
                description=f"Parameter: {param_name}",
                required=is_required,
                default=default_value
            ))
        
        # 创建工具定义
        tool_def = ToolDefinition(
            name=tool_name,
            description=tool_description,
            parameters=parameters,
            func=method,
            timeout=tool_timeout
        )
        
        self._tools[tool_name] = tool_def
    
    def _python_type_to_json_type(self, py_type: Type) -> str:
        """
        将Python类型转换为JSON Schema类型
        
        Args:
            py_type: Python类型
            
        Returns:
            JSON Schema类型字符串
        """
        type_mapping = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            list: "array",
            dict: "object",
            Any: "any"
        }
        
        # 处理Optional类型
        origin = getattr(py_type, '__origin__', None)
        if origin is not None:
            args = getattr(py_type, '__args__', ())
            if origin is not None and type(None) in args:
                # Optional[T] 的情况，取非None的类型
                for arg in args:
                    if arg is not type(None):
                        return self._python_type_to_json_type(arg)
        
        return type_mapping.get(py_type, "string")
    
    def get_tools(self) -> List[Dict[str, Any]]:
        """
        获取所有工具的定义列表（用于MCP工具发现）
        
        Returns:
            工具定义列表，格式符合MCP协议
        """
        tools = []
        for tool_def in self._tools.values():
            tool_schema = {
                "name": tool_def.name,
                "description": tool_def.description,
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
            
            for param in tool_def.parameters:
                tool_schema["inputSchema"]["properties"][param.name] = {
                    "type": param.type,
                    "description": param.description
                }
                if param.enum:
                    tool_schema["inputSchema"]["properties"][param.name]["enum"] = param.enum
                if param.default is not None:
                    tool_schema["inputSchema"]["properties"][param.name]["default"] = param.default
                
                if param.required:
                    tool_schema["inputSchema"]["required"].append(param.name)
            
            tools.append(tool_schema)
        
        return tools
    
    def get_tool_names(self) -> List[str]:
        """
        获取所有工具名称
        
        Returns:
            工具名称列表
        """
        return list(self._tools.keys())
    
    def has_tool(self, tool_name: str) -> bool:
        """
        检查是否包含指定工具
        
        Args:
            tool_name: 工具名称
            
        Returns:
            是否存在
        """
        return tool_name in self._tools
    
    def _validate_params(
        self,
        tool_def: ToolDefinition,
        params: Dict[str, Any]
    ) -> None:
        """
        验证工具参数
        
        Args:
            tool_def: 工具定义
            params: 传入的参数
            
        Raises:
            ToolValidationError: 验证失败
        """
        # 检查必填参数
        for param in tool_def.parameters:
            if param.required and param.name not in params:
                raise ToolValidationError(
                    f"Missing required parameter: {param.name}",
                    param_name=param.name
                )
            
            # 类型验证（可选）
            if param.name in params:
                value = params[param.name]
                if param.type == "integer" and not isinstance(value, int):
                    if not isinstance(value, float) or not value.is_integer():
                        raise ToolValidationError(
                            f"Parameter '{param.name}' should be integer",
                            param_name=param.name
                        )
                elif param.type == "number" and not isinstance(value, (int, float)):
                    raise ToolValidationError(
                        f"Parameter '{param.name}' should be number",
                        param_name=param.name
                    )
                elif param.type == "string" and not isinstance(value, str):
                    raise ToolValidationError(
                        f"Parameter '{param.name}' should be string",
                        param_name=param.name
                    )
                elif param.type == "boolean" and not isinstance(value, bool):
                    raise ToolValidationError(
                        f"Parameter '{param.name}' should be boolean",
                        param_name=param.name
                    )
    
    async def execute_tool(
        self,
        tool_name: str,
        params: Dict[str, Any]
    ) -> ToolResult:
        """
        执行指定工具
        
        Args:
            tool_name: 工具名称
            params: 工具参数
            
        Returns:
            工具执行结果
        """
        start_time = time.time()
        
        try:
            # 查找工具
            if tool_name not in self._tools:
                raise ToolNotFoundError(tool_name)
            
            tool_def = self._tools[tool_name]
            
            # 验证参数
            self._validate_params(tool_def, params)
            
            # 执行工具（带超时）
            try:
                result = await asyncio.wait_for(
                    tool_def.func(self, **params),
                    timeout=tool_def.timeout
                )
                
                execution_time = (time.time() - start_time) * 1000
                
                return ToolResult(
                    success=True,
                    data=result,
                    execution_time_ms=execution_time
                )
                
            except asyncio.TimeoutError:
                raise ToolTimeoutError(tool_name, tool_def.timeout)
                
        except SkillError as e:
            execution_time = (time.time() - start_time) * 1000
            return ToolResult(
                success=False,
                error=f"[{e.code}] {e.message}",
                execution_time_ms=execution_time
            )
        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            return ToolResult(
                success=False,
                error=error_msg,
                execution_time_ms=execution_time
            )
    
    @abstractmethod
    async def initialize(self) -> bool:
        """
        初始化Skill
        
        Returns:
            是否初始化成功
        """
        pass
    
    @abstractmethod
    async def cleanup(self) -> None:
        """
        清理Skill资源
        """
        pass
    
    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典表示
        
        Returns:
            Skill信息字典
        """
        return {
            "name": self.name,
            "description": self.description,
            "tools": self.get_tool_names(),
            "tool_count": len(self._tools)
        }
