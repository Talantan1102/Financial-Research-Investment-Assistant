#!/usr/bin/env python3
"""金融研投助手集成测试 - 原生 MCP Server 架构"""
import sys
import os
import asyncio
import json

os.environ['TUSHARE_API_TOKEN'] = '9e4123cf56aaa553b06556e64b05e9d8d004340d82897eb1704ccd91c088'
os.environ['TUSHARE_API_URL'] = 'http://lianghua.nanyangqiankun.top'

sys.path.insert(0, '/Users/talantan/.openclaw/workspace-dev/external/AgentFlow')
sys.path.insert(0, '/Users/talantan/.openclaw/workspace-dev/external/financial-research-assistant/backend')

from mcp.types import (
    ListResourcesRequest, ListToolsRequest,
    ReadResourceRequest, CallToolRequest
)


class TestFinanceMCPServer:
    """金融研投助手 MCP Server 测试类 - 原生 MCP 架构"""

    def __init__(self):
        self.server = None
        self.mcp_server = None

    async def setup(self):
        """初始化测试环境"""
        from sandbox.server.backends.resources.unified_finance import UnifiedFinanceMCPServer
        self.server = UnifiedFinanceMCPServer()
        self.mcp_server = self.server.server
        await self.server.warmup()
        print(f"✅ MCP Server 初始化成功")

    async def _call_list_resources(self):
        """调用 list_resources 处理器"""
        handler = self.mcp_server.request_handlers.get(ListResourcesRequest)
        if handler:
            result = await handler(ListResourcesRequest(method='resources/list'))
            return result.root.resources if hasattr(result, 'root') else result.resources
        return []

    async def _call_read_resource(self, uri: str):
        """调用 read_resource 处理器"""
        handler = self.mcp_server.request_handlers.get(ReadResourceRequest)
        if handler:
            result = await handler(ReadResourceRequest(
                method='resources/read',
                params={'uri': uri}
            ))
            return result.root.contents if hasattr(result, 'root') else result.contents
        return []

    async def _call_list_tools(self):
        """调用 list_tools 处理器"""
        handler = self.mcp_server.request_handlers.get(ListToolsRequest)
        if handler:
            result = await handler(ListToolsRequest(method='tools/list'))
            return result.root.tools if hasattr(result, 'root') else result.tools
        return []

    async def _call_call_tool(self, name: str, arguments: dict):
        """调用 call_tool 处理器"""
        handler = self.mcp_server.request_handlers.get(CallToolRequest)
        if handler:
            result = await handler(CallToolRequest(
                method='tools/call',
                params={'name': name, 'arguments': arguments}
            ))
            return result.root.content if hasattr(result, 'root') else result.content
        return []

    async def test_list_resources(self):
        """测试 Round 1: 获取 Skill Resources"""
        from mcp.types import Resource

        resources = await self._call_list_resources()

        print(f"✅ list_resources: 返回 {len(resources)} 个 Skills")
        assert len(resources) >= 7, f"Expected at least 7 skills, got {len(resources)}"
        for r in resources:
            assert isinstance(r, Resource), f"Expected Resource, got {type(r)}"
            assert str(r.uri).startswith('skill://')
        return True

    async def test_read_resource(self):
        """测试 Round 2: 读取 Skill Resource"""
        contents = await self._call_read_resource("skill://market_data")

        assert len(contents) > 0
        content = contents[0]
        text = content.text if hasattr(content, 'text') else str(content)
        assert 'SKILL' in text or 'market_data' in text

        # 验证 skill 被标记为 discovered
        assert 'market_data' in self.server._discovered_skills

        print(f"✅ read_resource: 成功加载 market_data Skill")
        return True

    async def test_list_tools(self):
        """测试 Round 3: 获取工具列表"""
        from mcp.types import Tool

        # 先读取 resource 使其被标记为 discovered
        await self._call_read_resource("skill://market_data")

        tools = await self._call_list_tools()

        print(f"✅ list_tools: 返回 {len(tools)} 个 Tools")
        assert len(tools) > 0, "Expected at least 1 tool"
        # 检查工具名格式为 skill_name.tool_name
        for tool in tools:
            assert isinstance(tool, Tool), f"Expected Tool, got {type(tool)}"
            assert '.' in tool.name, f"Tool name should be 'skill_name.tool_name', got {tool.name}"
        return True

    async def test_call_tool(self):
        """测试 Round 4: 调用工具"""
        from mcp.types import TextContent

        # 先读取 resource 使其被标记为 discovered
        await self._call_read_resource("skill://market_data")

        result = await self._call_call_tool(
            name='market_data.get_quote',
            arguments={'symbol': '600519'}
        )

        assert len(result) > 0
        assert isinstance(result[0], TextContent), f"Expected TextContent, got {type(result[0])}"
        assert result[0].type == "text"

        result_data = json.loads(result[0].text)
        assert result_data.get('success') == True or 'name' in result_data or 'data' in result_data

        print(f"✅ call_tool: 成功调用 market_data.get_quote")
        return True

    async def test_full_workflow(self):
        """测试完整的新架构工作流"""
        print("\n--- 测试完整工作流 ---")

        # Round 1: List resources
        resources = await self._call_list_resources()
        print(f"Round 1 - 发现 {len(resources)} 个 Skills")
        assert len(resources) >= 7

        # Round 2: Read resources
        for resource in resources[:3]:  # 测试前3个
            uri = str(resource.uri)
            contents = await self._call_read_resource(uri)
            assert len(contents) > 0
            print(f"Round 2 - 读取 {uri}: 成功")

        # Round 3: List tools
        tools = await self._call_list_tools()
        print(f"Round 3 - 发现 {len(tools)} 个 Tools")
        assert len(tools) > 0

        # Round 4: Call a tool
        if tools:
            # 找一个 market_data.get_quote 工具
            quote_tool = None
            for t in tools:
                if 'get_quote' in t.name:
                    quote_tool = t.name
                    break

            if quote_tool:
                result = await self._call_call_tool(
                    name=quote_tool,
                    arguments={'symbol': '600519'}
                )
                assert len(result) > 0
                print(f"Round 4 - 调用 {quote_tool}: 成功")

        print("✅ 完整工作流测试通过")
        return True

    async def test_return_types(self):
        """测试返回类型是否为原生 MCP 类型"""
        from mcp.types import Resource, Tool, TextContent

        # Test list_resources returns List[Resource]
        resources = await self._call_list_resources()
        for r in resources:
            assert isinstance(r, Resource), f"Expected Resource, got {type(r)}"

        # Test read_resource returns correct type
        contents = await self._call_read_resource("skill://market_data")
        for c in contents:
            assert hasattr(c, 'text'), f"Expected content with text attr, got {type(c)}"

        # Test list_tools returns List[Tool]
        tools = await self._call_list_tools()
        for t in tools:
            assert isinstance(t, Tool), f"Expected Tool, got {type(t)}"

        # Test call_tool returns List[TextContent]
        result = await self._call_call_tool(
            name='market_data.get_quote',
            arguments={'symbol': '600519'}
        )
        for r in result:
            assert isinstance(r, TextContent), f"Expected TextContent, got {type(r)}"

        print("✅ 返回类型检查通过（原生 MCP 类型）")
        return True

    async def test_server_structure(self):
        """测试 Server 结构符合原生 MCP 标准"""
        from mcp.server import Server

        # 验证 server 是原生 MCP Server 实例
        assert isinstance(self.mcp_server, Server), \
            f"Expected Server, got {type(self.mcp_server)}"

        # 验证处理器已注册
        handlers = self.mcp_server.request_handlers
        assert handlers is not None, "Server should have registered handlers"

        # 验证关键处理器存在
        assert ListResourcesRequest in handlers, "Missing ListResourcesRequest handler"
        assert ReadResourceRequest in handlers, "Missing ReadResourceRequest handler"
        assert ListToolsRequest in handlers, "Missing ListToolsRequest handler"
        assert CallToolRequest in handlers, "Missing CallToolRequest handler"

        print("✅ Server 结构检查通过（原生 MCP Server）")
        return True

    async def run_all(self):
        """运行所有测试"""
        print("=" * 60)
        print("🧪 金融研投助手 MCP Server 测试 - 原生 MCP 架构")
        print("=" * 60)
        await self.setup()

        print("\n--- 结构测试 ---")
        await self.test_server_structure()

        print("\n--- 基础功能测试 ---")
        await self.test_list_resources()
        await self.test_read_resource()
        await self.test_list_tools()
        await self.test_call_tool()

        print("\n--- 完整工作流测试 ---")
        await self.test_full_workflow()

        print("\n--- 返回类型测试 ---")
        await self.test_return_types()

        print("\n" + "=" * 60)
        print("✅ 所有测试通过!")
        print("=" * 60)
        print("\n重构验证:")
        print("1. ✅ UnifiedFinanceMCPServer 使用原生 MCP Server")
        print("2. ✅ list_resources() 返回 List[Resource]")
        print("3. ✅ read_resource() 返回正确类型")
        print("4. ✅ list_tools() 返回 List[Tool]")
        print("5. ✅ call_tool() 返回 List[TextContent]")
        print("6. ✅ Server 结构符合原生 MCP 标准")


if __name__ == "__main__":
    test = TestFinanceMCPServer()
    asyncio.run(test.run_all())
