#!/usr/bin/env python3
"""金融研投助手 MCP Server 单元测试 - 验证原生 MCP 架构"""
import sys
import os
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, '/Users/talantan/.openclaw/workspace-dev/external/AgentFlow')
sys.path.insert(0, '/Users/talantan/.openclaw/workspace-dev/external/financial-research-assistant/backend')

from mcp.types import (
    ListResourcesRequest, ListToolsRequest,
    ReadResourceRequest, CallToolRequest,
    Resource, Tool, TextContent
)
from mcp.server import Server


class MockSkill:
    """Mock Skill 用于测试"""
    def __init__(self, name):
        self.name = name

    def discover_tools_json(self):
        return [
            {
                'name': 'get_quote',
                'description': 'Get stock quote',
                'parameters': {
                    'type': 'object',
                    'properties': {'symbol': {'type': 'string'}},
                    'required': ['symbol']
                }
            }
        ]

    def has_tool(self, tool_name):
        return tool_name == 'get_quote'

    async def execute_tool(self, tool_name, arguments):
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            'success': True,
            'symbol': arguments.get('symbol'),
            'price': 100.0
        }
        return mock_result


class TestFinanceResearchServer:
    """测试 FinanceResearchServer 原生 MCP 实现"""

    def __init__(self):
        self.server = None

    async def setup(self):
        """初始化测试环境 - 使用 Mock Skills"""
        from sandbox.server.backends.resources import FinanceResearchServer
        self.server = FinanceResearchServer()

        # 手动设置 mock skills
        self.server.skills = {
            'market_data': MockSkill('market_data'),
        }

        # 手动加载 metadata
        self.server.skill_metadata = {
            'market_data': {
                'name': 'market_data',
                'description': 'Market data skill for stock quotes'
            }
        }

        print(f"✅ MCP Server 初始化成功 (使用 Mock Skills)")

    async def _call_list_resources(self):
        """调用 list_resources 处理器"""
        handler = self.server.server.request_handlers.get(ListResourcesRequest)
        if handler:
            result = await handler(ListResourcesRequest(method='resources/list'))
            return result.root.resources if hasattr(result, 'root') else result.resources
        return []

    async def _call_read_resource(self, uri: str):
        """调用 read_resource 处理器"""
        from pydantic import AnyUrl
        handler = self.server.server.request_handlers.get(ReadResourceRequest)
        if handler:
            result = await handler(ReadResourceRequest(
                method='resources/read',
                params={'uri': AnyUrl(uri)}
            ))
            # 返回字符串内容
            if hasattr(result, 'root'):
                contents = result.root.contents
            else:
                contents = result.contents
            # 读取字符串内容（返回的是 TextResourceContents）
            return contents
        return []

    async def _call_list_tools(self):
        """调用 list_tools 处理器"""
        handler = self.server.server.request_handlers.get(ListToolsRequest)
        if handler:
            result = await handler(ListToolsRequest(method='tools/list'))
            return result.root.tools if hasattr(result, 'root') else result.tools
        return []

    async def _call_call_tool(self, name: str, arguments: dict):
        """调用 call_tool 处理器"""
        handler = self.server.server.request_handlers.get(CallToolRequest)
        if handler:
            result = await handler(CallToolRequest(
                method='tools/call',
                params={'name': name, 'arguments': arguments}
            ))
            return result.root.content if hasattr(result, 'root') else result.content
        return []

    async def test_server_is_native_mcp(self):
        """测试 Server 是原生 MCP Server"""
        assert isinstance(self.server.server, Server), \
            f"Expected Server, got {type(self.server.server)}"
        print("✅ Server 是原生 MCP Server 实例")

    async def test_list_resources_returns_mcp_types(self):
        """测试 list_resources 返回原生 MCP Resource 类型"""
        resources = await self._call_list_resources()

        assert len(resources) == 1, f"Expected 1 resource, got {len(resources)}"
        assert isinstance(resources[0], Resource), \
            f"Expected Resource, got {type(resources[0])}"
        assert str(resources[0].uri).startswith('skill://')
        print("✅ list_resources 返回 List[Resource]")

    async def test_read_resource_updates_discovered(self):
        """测试 read_resource 更新 discovered_skills"""
        # 初始状态
        assert 'market_data' not in self.server._discovered_skills

        contents = await self._call_read_resource("skill://market_data")

        # 验证 discovered_skills 被更新
        assert 'market_data' in self.server._discovered_skills
        print("✅ read_resource 正确更新 discovered_skills")

    async def test_list_tools_returns_mcp_types(self):
        """测试 list_tools 返回原生 MCP Tool 类型"""
        # 先读取 resource
        await self._call_read_resource("skill://market_data")

        tools = await self._call_list_tools()

        assert len(tools) == 1, f"Expected 1 tool, got {len(tools)}"
        assert isinstance(tools[0], Tool), f"Expected Tool, got {type(tools[0])}"
        assert tools[0].name == 'market_data.get_quote'
        print("✅ list_tools 返回 List[Tool]")

    async def test_call_tool_returns_mcp_types(self):
        """测试 call_tool 返回原生 MCP TextContent 类型"""
        # 先读取 resource
        await self._call_read_resource("skill://market_data")

        result = await self._call_call_tool(
            name='market_data.get_quote',
            arguments={'symbol': '600519'}
        )

        assert len(result) == 1, f"Expected 1 result, got {len(result)}"
        assert isinstance(result[0], TextContent), \
            f"Expected TextContent, got {type(result[0])}"
        assert result[0].type == "text"

        # 验证返回的 JSON 数据
        data = json.loads(result[0].text)
        assert data['success'] == True
        assert data['symbol'] == '600519'
        print("✅ call_tool 返回 List[TextContent]")

    async def test_handlers_registered(self):
        """测试所有处理器已正确注册"""
        handlers = self.server.server.request_handlers

        assert ListResourcesRequest in handlers, "Missing ListResourcesRequest handler"
        assert ReadResourceRequest in handlers, "Missing ReadResourceRequest handler"
        assert ListToolsRequest in handlers, "Missing ListToolsRequest handler"
        assert CallToolRequest in handlers, "Missing CallToolRequest handler"
        print("✅ 所有 MCP 处理器已注册")

    async def test_no_backend_inheritance(self):
        """测试不再继承 Backend 基类"""
        from sandbox.server.backends.base import Backend

        assert not isinstance(self.server, Backend), \
            "Server should not inherit from Backend"
        assert not hasattr(self.server, 'name') or self.server.__class__.__name__ != 'Backend', \
            "Server should not be Backend instance"
        print("✅ FinanceResearchServer 不继承 Backend 基类")

    async def test_no_tool_decorator(self):
        """测试不再使用 @tool 装饰器"""
        # 检查类定义中没有 tool 装饰器的痕迹
        # 如果使用了 @tool 装饰器，会有特定的标记
        import inspect
        source = inspect.getsource(self.server.__class__)
        assert '@tool' not in source, "Should not use @tool decorator"
        print("✅ 不再使用 @tool 装饰器")

    async def test_backwards_compat_exports(self):
        """测试向后兼容导出"""
        from sandbox.server.backends.resources import (
            FinanceResearchBackend,
        )

        # FinanceResearchBackend 应该指向 FinanceResearchServer
        assert FinanceResearchBackend is FinanceResearchServer, \
            "FinanceResearchBackend should be alias for FinanceResearchServer"
        print("✅ 向后兼容导出正确")

    async def test_class_name_is_business_related(self):
        """测试类名是业务相关名称"""
        # 新类名应该包含业务相关词汇
        class_name = self.server.__class__.__name__
        business_keywords = ['Finance', 'Research', 'Financial']
        has_business_keyword = any(kw in class_name for kw in business_keywords)

        # 不应该包含技术/架构前缀
        tech_prefixes = ['Unified', 'AgentFlow', 'MCP', 'Backend']
        has_tech_prefix = any(prefix in class_name for prefix in tech_prefixes)

        assert has_business_keyword, \
            f"Class name '{class_name}' should contain business keyword"
        assert not has_tech_prefix, \
            f"Class name '{class_name}' should not contain tech prefix like Unified/AgentFlow/MCP/Backend"

        print(f"✅ 类名 '{class_name}' 是业务相关名称")

    async def run_all(self):
        """运行所有测试"""
        print("=" * 60)
        print("🧪 FinanceResearchServer 单元测试 - 原生 MCP 验证")
        print("=" * 60)
        await self.setup()

        print("\n--- 架构验证 ---")
        await self.test_no_backend_inheritance()
        await self.test_no_tool_decorator()
        await self.test_handlers_registered()
        await self.test_server_is_native_mcp()
        await self.test_class_name_is_business_related()
        await self.test_backwards_compat_exports()

        print("\n--- 功能测试 ---")
        await self.test_list_resources_returns_mcp_types()
        await self.test_read_resource_updates_discovered()
        await self.test_list_tools_returns_mcp_types()
        await self.test_call_tool_returns_mcp_types()

        print("\n" + "=" * 60)
        print("✅ 所有测试通过!")
        print("=" * 60)
        print("\n重构验证:")
        print("1. ✅ FinanceResearchServer 是原生 MCP Server")
        print("2. ✅ 类名是业务相关名称（FinanceResearch）")
        print("3. ✅ 不再继承 Backend 基类")
        print("4. ✅ 不再使用 @tool 装饰器")
        print("5. ✅ list_resources() 返回 List[Resource]")
        print("6. ✅ read_resource() 更新 discovered_skills")
        print("7. ✅ list_tools() 返回 List[Tool]")
        print("8. ✅ call_tool() 返回 List[TextContent]")
        print("9. ✅ 向后兼容导出保留")


if __name__ == "__main__":
    from sandbox.server.backends.resources import FinanceResearchServer

    test = TestFinanceResearchServer()
    asyncio.run(test.run_all())
