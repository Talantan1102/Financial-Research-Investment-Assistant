# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""Skill 基类 - MCP Server 工具抽象基类

参考 ToolExecutor 设计，提供统一的工具注册、发现和执行接口。
"""

import asyncio
import logging
import os
import traceback
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# 配置日志只输出到文件，避免干扰 MCP STDIO 通信
_log_file = os.path.join(os.path.dirname(__file__), "skills.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(_log_file)],
)


@dataclass
class ToolParameter:
    """工具参数定义（保留用于向后兼容，但不再用于MCP工具注册）"""

    name: str
    type: str  # string, number, integer, boolean, array, object
    description: str
    required: bool = True
    default: Any = None
    enum: list[Any] | None = None


@dataclass
class ToolDefinition:
    """工具定义（保留用于向后兼容，但不再用于MCP工具注册）"""

    name: str
    description: str
    parameters: list[ToolParameter]

    def to_json_schema(self) -> dict[str, Any]:
        """转换为 JSON Schema 格式（保留用于向后兼容）"""
        properties = {}
        required = []

        for param in self.parameters:
            prop = {"type": param.type, "description": param.description}
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
            "parameters": {"type": "object", "properties": properties, "required": required},
        }


@dataclass
class ToolResult:
    """工具执行结果"""

    success: bool
    data: Any | None = None
    error: str | None = None
    meta: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {"success": self.success, "data": self.data, "error": self.error, "meta": self.meta}


class BaseSkill(ABC):
    """
    Skill 基类（简化版 - 用于Claude Skills架构）

    现在Skills通过SKILL.md文件定义，不再通过Python代码注册MCP工具。
    BaseSkill类仅作为后端工具实现的容器，提供工具方法供SKILL.md中的Bash命令调用。

    示例：
        class MySkill(BaseSkill):
            name = "my_skill"
            description = "My skill description"

            def _register_tools(self):
                # 保留注册逻辑用于向后兼容和内部调用
                self.register_tool(
                    name="my_tool",
                    handler=self.my_tool_handler,
                    description="Tool description",
                    parameters=[...]
                )

            async def my_tool_handler(self, param1: str):
                # 实际的工具实现
                return ToolResult(success=True, data={"result": "..."})
    """

    name: str = ""
    description: str = ""

    def __init__(self, name: str = None, description: str = None):
        self.name = name or self.__class__.name or self.__class__.__name__
        self.description = description or self.__class__.description or ""
        self._tools: dict[str, Callable] = {}
        self._tool_definitions: dict[str, ToolDefinition] = {}
        self._logger = logging.getLogger(self.name)
        self._initialized = False
        # 保留注册逻辑用于向后兼容
        self._register_tools()

    @abstractmethod
    def _register_tools(self):
        """
        注册工具，子类必须实现（保留用于向后兼容）

        注意：在Claude Skills架构下，工具定义在SKILL.md中，
        这里的注册主要用于内部工具映射和直接调用。
        """
        pass

    def register_tool(
        self, name: str, handler: Callable, description: str, parameters: list[ToolParameter]
    ):
        """
        注册工具（保留用于向后兼容和内部调用）

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
            name=name, description=description, parameters=parameters
        )
        self._logger.debug(f"已注册工具: {name}")

    def discover_tools(self) -> list[ToolDefinition]:
        """
        发现所有可用的工具（保留用于向后兼容）

        Returns:
            工具定义列表
        """
        return list(self._tool_definitions.values())

    def discover_tools_json(self) -> list[dict[str, Any]]:
        """
        发现所有可用的工具（JSON Schema 格式）（保留用于向后兼容）

        Returns:
            工具定义列表（JSON Schema）
        """
        return [tool.to_json_schema() for tool in self.discover_tools()]

    async def execute_tool(self, tool_name: str, params: dict[str, Any]) -> ToolResult:
        """
        执行指定工具（保留用于内部调用）

        Args:
            tool_name: 工具名称
            params: 工具参数

        Returns:
            ToolResult 执行结果
        """
        if tool_name not in self._tools:
            return ToolResult(
                success=False, error=f"工具 '{tool_name}' 不存在于 Skill '{self.name}'"
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
            return ToolResult(success=False, error=f"工具执行失败: {str(e)}")

    def _validate_params(self, params: dict[str, Any], tool_def: ToolDefinition) -> str | None:
        """
        参数校验（保留用于内部调用）

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
                "object": dict,
            }

            expected_type = type_map.get(param_def.type)
            if expected_type and not isinstance(value, expected_type):
                return f"参数 '{param_name}' 类型错误，期望 {param_def.type}"

        return None

    def get_tool_handler(self, tool_name: str) -> Callable | None:
        """
        获取工具处理器（保留用于向后兼容）

        Args:
            tool_name: 工具名称

        Returns:
            工具处理器函数，不存在返回 None
        """
        return self._tools.get(tool_name)

    def has_tool(self, tool_name: str) -> bool:
        """
        检查是否包含指定工具（保留用于向后兼容）

        Args:
            tool_name: 工具名称

        Returns:
            是否存在
        """
        return tool_name in self._tools

    def get_skill_md(self) -> str:
        """
        获取 Skill 的 SKILL.md 文档内容

        Returns:
            SKILL.md 文件内容，如果不存在返回默认描述
        """
        # 获取 skill 文件路径
        skill_file = os.path.join(os.path.dirname(__file__), f"{self.name}.py")

        # 检查对应的 SKILL.md 文件
        skill_md_path = os.path.join(os.path.dirname(__file__), f"{self.name}", "SKILL.md")

        # 如果 SKILL.md 存在，读取内容
        if os.path.exists(skill_md_path):
            try:
                with open(skill_md_path, encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                self._logger.error(f"读取 SKILL.md 失败: {e}")

        # 如果不存在，生成默认的 SKILL.md 内容
        return self._generate_default_skill_md()

    def _generate_default_skill_md(self) -> str:
        """生成默认的 SKILL.md 内容"""
        tools_md = []
        for name, tool_def in self._tool_definitions.items():
            params_str = ", ".join(
                [
                    f"{p.name}: {p.type}" + (" (required)" if p.required else "")
                    for p in tool_def.parameters
                ]
            )
            tools_md.append(f"### {name}")
            tools_md.append(f"- 描述: {tool_def.description}")
            tools_md.append(f"- 参数: {params_str}")
            tools_md.append("")

        return f"""---
title: {self.name}
description: {self.description}
---

# {self.name}

{self.description}

## 可用工具

{chr(10).join(tools_md)}

## 使用示例

待补充...
"""

    @property
    def tool_count(self) -> int:
        """工具数量（保留用于向后兼容）"""
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
