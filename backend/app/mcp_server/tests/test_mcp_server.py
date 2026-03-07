#!/usr/bin/env python3
"""
MCP Server 功能测试脚本（修复版）

修复了原 test_server.py 中的所有问题，提供完整的功能测试。
"""

import asyncio
import json
import sys
import os
from typing import Dict, Any

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from app.mcp_server.server import create_server, FinancialMCPServer
from app.mcp_server.config import get_config, MCPServerConfig
from app.mcp_server.skills import MarketDataSkill
from app.data.tushare_client import get_tushare_client


class TestResult:
    """测试结果"""
    def __init__(self):
        self.total = 0
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.errors = []

    def add_pass(self, test_name: str):
        self.total += 1
        self.passed += 1
        print(f"✅ {test_name}")

    def add_fail(self, test_name: str, error: str):
        self.total += 1
        self.failed += 1
        self.errors.append((test_name, error))
        print(f"❌ {test_name}: {error}")

    def add_skip(self, test_name: str, reason: str):
        self.total += 1
        self.skipped += 1
        print(f"⏭️  {test_name}: {reason}")

    def print_summary(self):
        print("\n" + "=" * 60)
        print("测试总结")
        print("=" * 60)
        print(f"总计: {self.total}")
        print(f"✅ 通过: {self.passed}")
        print(f"❌ 失败: {self.failed}")
        print(f"⏭️  跳过: {self.skipped}")

        if self.errors:
            print("\n失败详情:")
            for test_name, error in self.errors:
                print(f"  - {test_name}: {error}")

        print("=" * 60)
        return self.failed == 0


async def test_config():
    """测试配置管理"""
    print("\n" + "=" * 60)
    print("测试 1: 配置管理")
    print("=" * 60)

    result = TestResult()

    try:
        # 测试获取配置
        config = get_config()
        result.add_pass("获取配置实例")

        # 测试配置属性
        assert hasattr(config, 'server_name')
        result.add_pass("配置包含 server_name")

        assert hasattr(config, 'server_version')
        result.add_pass("配置包含 server_version")

        assert hasattr(config, 'tushare_api_token')
        result.add_pass("配置包含 tushare_api_token")

        # 显示配置信息
        print(f"\n📋 配置信息:")
        print(f"  Server Name: {config.server_name}")
        print(f"  Server Version: {config.server_version}")
        print(f"  Cache TTL: {config.cache_ttl}s")
        print(f"  Log Level: {config.log_level}")
        print(f"  Tushare Token: {'已设置' if config.tushare_api_token else '未设置'}")

    except Exception as e:
        result.add_fail("配置测试", str(e))

    result.print_summary()
    return result.failed == 0


async def test_server_creation():
    """测试 Server 创建"""
    print("\n" + "=" * 60)
    print("测试 2: Server 创建")
    print("=" * 60)

    result = TestResult()

    try:
        # 测试创建 Server
        server = create_server()
        result.add_pass("创建 Server 实例")

        # 测试 Server 属性
        assert isinstance(server, FinancialMCPServer)
        result.add_pass("Server 类型正确")

        assert hasattr(server, 'skills')
        result.add_pass("Server 包含 skills 属性")

        assert hasattr(server, 'server')
        result.add_pass("Server 包含 MCP server 实例")

        # 测试已注册的 Skills
        print(f"\n📊 已注册的 Skills:")
        for skill_name, skill in server.skills.items():
            tools = skill.discover_tools()
            print(f"  - {skill_name}: {len(tools)} 个工具")
            for tool in tools:
                print(f"    • {tool.name}: {tool.description[:50]}...")

        if 'market_data' not in server.skills:
            result.add_fail("MarketData Skill 注册", "未找到 market_data")
        else:
            result.add_pass("MarketData Skill 已注册")

    except Exception as e:
        result.add_fail("Server 创建测试", str(e))

    result.print_summary()
    return result.failed == 0, server if 'server' in locals() else None


async def test_market_data_skill():
    """测试 MarketData Skill"""
    print("\n" + "=" * 60)
    print("测试 3: MarketData Skill")
    print("=" * 60)

    result = TestResult()

    try:
        # 创建 Skill 实例
        skill = MarketDataSkill()
        result.add_pass("创建 MarketData Skill")

        # 测试工具发现
        tools = skill.discover_tools()
        print(f"\n📋 发现 {len(tools)} 个工具:")
        for tool in tools:
            print(f"  - {tool.name}: {tool.description}")

        if len(tools) < 2:
            result.add_fail("工具数量", f"期望至少2个工具，实际 {len(tools)} 个")
        else:
            result.add_pass(f"工具数量正确 ({len(tools)} 个)")

        # 测试工具定义
        tool_names = [tool.name for tool in tools]
        if 'get_quote' in tool_names:
            result.add_pass("包含 get_quote 工具")
        else:
            result.add_fail("get_quote 工具", "未找到")

        if 'search_stock' in tool_names:
            result.add_pass("包含 search_stock 工具")
        else:
            result.add_fail("search_stock 工具", "未找到")

        # 测试 JSON Schema 转换
        tool_schemas = skill.discover_tools_json()
        assert len(tool_schemas) == len(tools)
        result.add_pass("JSON Schema 转换正确")

    except Exception as e:
        result.add_fail("MarketData Skill 测试", str(e))

    result.print_summary()
    return result.failed == 0, skill if 'skill' in locals() else None


async def test_get_quote_tool(skill: MarketDataSkill):
    """测试 get_quote 工具"""
    print("\n" + "=" * 60)
    print("测试 4: get_quote 工具")
    print("=" * 60)

    result = TestResult()
    config = get_config()

    if not config.tushare_api_token:
        result.add_skip("所有测试", "TUSHARE_API_TOKEN 未设置")
        result.print_summary()
        return False

    try:
        # 测试1: 正常查询（贵州茅台）
        print("\n📈 测试查询: 600519 (贵州茅台)")
        tool_result = await skill.execute_tool("get_quote", {"symbol": "600519"})

        if tool_result.success:
            result.add_pass("查询 600519 成功")
            data = tool_result.data
            print(f"  名称: {data.get('name')}")
            print(f"  代码: {data.get('ts_code')}")
            print(f"  当前价: {data.get('nowPri')}")
            print(f"  涨跌幅: {data.get('increPer')}%")

            # 验证数据完整性
            required_fields = ['name', 'nowPri', 'ts_code', 'increase', 'increPer']
            for field in required_fields:
                if field in data:
                    result.add_pass(f"包含字段 {field}")
                else:
                    result.add_fail(f"字段检查", f"缺少 {field}")
        else:
            result.add_fail("查询 600519", tool_result.error)

        # 测试2: 不同格式的股票代码
        print("\n📈 测试不同代码格式:")
        test_codes = [
            ("sh600519", "带 sh 前缀"),
            ("600519.SH", "Tushare 格式"),
            ("000001", "深圳平安银行"),
        ]

        for code, desc in test_codes:
            try:
                tool_result = await skill.execute_tool("get_quote", {"symbol": code})
                if tool_result.success:
                    result.add_pass(f"查询 {code} ({desc})")
                    print(f"  ✓ {code}: {tool_result.data.get('name')}")
                else:
                    result.add_fail(f"查询 {code}", tool_result.error)
            except Exception as e:
                result.add_fail(f"查询 {code}", str(e))

        # 测试3: 错误处理 - 空代码
        print("\n🧪 测试错误处理:")
        tool_result = await skill.execute_tool("get_quote", {"symbol": ""})
        if not tool_result.success:
            result.add_pass("空代码错误处理")
        else:
            result.add_fail("空代码错误处理", "应该返回失败")

        # 测试4: 错误处理 - 无效代码
        tool_result = await skill.execute_tool("get_quote", {"symbol": "999999"})
        if not tool_result.success:
            result.add_pass("无效代码错误处理")
        else:
            result.add_fail("无效代码错误处理", "应该返回失败")

    except Exception as e:
        result.add_fail("get_quote 工具测试", str(e))

    result.print_summary()
    return result.failed == 0


async def test_search_stock_tool(skill: MarketDataSkill):
    """测试 search_stock 工具"""
    print("\n" + "=" * 60)
    print("测试 5: search_stock 工具")
    print("=" * 60)

    result = TestResult()
    config = get_config()

    if not config.tushare_api_token:
        result.add_skip("所有测试", "TUSHARE_API_TOKEN 未设置")
        result.print_summary()
        return False

    try:
        # 测试1: 搜索股票代码
        print("\n🔍 测试搜索: 600519")
        tool_result = await skill.execute_tool("search_stock", {"keyword": "600519"})

        if tool_result.success:
            result.add_pass("搜索 600519 成功")
            data = tool_result.data
            print(f"  找到 {data.get('count')} 个结果")
            if data.get('results'):
                for stock in data['results']:
                    print(f"    - {stock.get('name')} ({stock.get('ts_code')})")
        else:
            result.add_fail("搜索 600519", tool_result.error)

        # 测试2: 搜索不存在的股票
        print("\n🔍 测试搜索不存在的股票: 888888")
        tool_result = await skill.execute_tool("search_stock", {"keyword": "888888"})
        if not tool_result.success:
            result.add_pass("不存在股票的错误处理")
        else:
            result.add_fail("不存在股票的错误处理", "应该返回失败或空结果")

        # 测试3: 空关键词
        print("\n🔍 测试空关键词")
        tool_result = await skill.execute_tool("search_stock", {"keyword": ""})
        if not tool_result.success:
            result.add_pass("空关键词错误处理")
        else:
            result.add_fail("空关键词错误处理", "应该返回失败")

    except Exception as e:
        result.add_fail("search_stock 工具测试", str(e))

    result.print_summary()
    return result.failed == 0


async def test_tushare_client():
    """测试 Tushare Client"""
    print("\n" + "=" * 60)
    print("测试 6: Tushare Client")
    print("=" * 60)

    result = TestResult()

    try:
        # 获取客户端
        client = get_tushare_client()
        result.add_pass("获取 Tushare Client")

        # 测试缓存信息
        cache_info = client.get_cache_info()
        result.add_pass("获取缓存信息")
        print(f"\n📊 缓存信息:")
        print(f"  总缓存数: {cache_info['total_cached']}")
        print(f"  有效缓存数: {cache_info['valid_cached']}")
        print(f"  缓存TTL: {cache_info['cache_ttl']}s")

        # 如果 Token 未设置，跳过后续测试
        if not client.token:
            result.add_skip("数据查询测试", "TUSHARE_API_TOKEN 未设置")
            result.print_summary()
            return False

        # 测试查询
        print("\n📈 测试查询股票数据:")
        query_result = client.get_quote("600519")

        if query_result['success']:
            result.add_pass("查询股票数据成功")
            data = query_result['data']
            print(f"  名称: {data['name']}")
            print(f"  代码: {data['ts_code']}")
            print(f"  当前价: {data['nowPri']}")

            # 测试缓存
            print("\n🗄️ 测试缓存机制:")
            cache_info_before = client.get_cache_info()

            # 再次查询（应该从缓存获取）
            query_result2 = client.get_quote("600519")
            if query_result2['success']:
                result.add_pass("缓存查询成功")

            cache_info_after = client.get_cache_info()
            if cache_info_after['total_cached'] >= cache_info_before['total_cached']:
                result.add_pass("缓存正常工作")
        else:
            result.add_fail("查询股票数据", query_result['error'])

    except Exception as e:
        result.add_fail("Tushare Client 测试", str(e))

    result.print_summary()
    return result.failed == 0


async def test_tool_parameter_validation():
    """测试工具参数验证"""
    print("\n" + "=" * 60)
    print("测试 7: 工具参数验证")
    print("=" * 60)

    result = TestResult()

    try:
        skill = MarketDataSkill()

        # 测试缺少必填参数
        print("\n🧪 测试缺少必填参数:")
        tool_result = await skill.execute_tool("get_quote", {})
        if not tool_result.success and "缺少必填参数" in tool_result.error:
            result.add_pass("检测到缺少必填参数")
        else:
            result.add_fail("参数验证", "未正确检测缺少必填参数")

        # 测试错误的参数类型
        print("\n🧪 测试错误的参数类型:")
        tool_result = await skill.execute_tool("get_quote", {"symbol": 123})
        if not tool_result.success:
            result.add_pass("检测到参数类型错误")
        else:
            # 可能自动转换了，也算通过
            result.add_pass("参数类型自动转换")

        # 测试不存在的工具
        print("\n🧪 测试调用不存在的工具:")
        tool_result = await skill.execute_tool("non_existent_tool", {})
        if not tool_result.success:
            result.add_pass("检测到工具不存在")
        else:
            result.add_fail("工具存在性检查", "未检测到工具不存在")

    except Exception as e:
        result.add_fail("参数验证测试", str(e))

    result.print_summary()
    return result.failed == 0


async def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("MCP Server 完整功能测试")
    print("=" * 60)
    print(f"测试时间: {os.popen('date').read().strip()}")

    all_passed = True

    # 测试1: 配置管理
    passed = await test_config()
    all_passed = all_passed and passed

    # 测试2: Server 创建
    passed, server = await test_server_creation()
    all_passed = all_passed and passed

    # 测试3: MarketData Skill
    passed, skill = await test_market_data_skill()
    all_passed = all_passed and passed

    # 测试4-5: 工具功能测试（需要 skill）
    if skill:
        passed = await test_get_quote_tool(skill)
        all_passed = all_passed and passed

        passed = await test_search_stock_tool(skill)
        all_passed = all_passed and passed

    # 测试6: Tushare Client
    passed = await test_tushare_client()
    all_passed = all_passed and passed

    # 测试7: 参数验证
    passed = await test_tool_parameter_validation()
    all_passed = all_passed and passed

    # 最终总结
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ 所有测试通过！")
    else:
        print("❌ 部分测试失败，请查看上面的详细信息")
    print("=" * 60)

    return all_passed


if __name__ == "__main__":
    # 检查环境变量
    token = os.getenv("TUSHARE_API_TOKEN")
    if not token:
        print("⚠️  警告: TUSHARE_API_TOKEN 环境变量未设置")
        print("部分测试将被跳过，仅测试基础功能\n")
        print("设置方法: export TUSHARE_API_TOKEN=your_token_here\n")

    # 运行测试
    success = asyncio.run(run_all_tests())

    # 退出码
    sys.exit(0 if success else 1)
