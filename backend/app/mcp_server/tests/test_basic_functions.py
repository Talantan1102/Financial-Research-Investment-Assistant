#!/usr/bin/env python3
"""
MCP Server 基础功能测试（不依赖 MCP SDK）

仅测试 Skills 和 Data 层的核心逻辑，不需要安装 mcp 包。
"""

import asyncio
import json
import sys
import os
from typing import Dict, Any

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))


class TestResult:
    """测试结果"""
    def __init__(self, name: str):
        self.name = name
        self.total = 0
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.errors = []

    def add_pass(self, test_name: str):
        self.total += 1
        self.passed += 1
        print(f"  ✅ {test_name}")

    def add_fail(self, test_name: str, error: str):
        self.total += 1
        self.failed += 1
        self.errors.append((test_name, error))
        print(f"  ❌ {test_name}")
        print(f"     错误: {error}")

    def add_skip(self, test_name: str, reason: str):
        self.total += 1
        self.skipped += 1
        print(f"  ⏭️  {test_name} (跳过: {reason})")

    def print_summary(self):
        print(f"\n  总计: {self.total} | ✅ {self.passed} | ❌ {self.failed} | ⏭️  {self.skipped}")
        if self.errors:
            print(f"\n  失败详情:")
            for test_name, error in self.errors:
                print(f"    - {test_name}: {error}")


async def test_tushare_client():
    """测试 Tushare Client（最底层）"""
    print("\n" + "=" * 70)
    print("测试 1: Tushare Client (数据层)")
    print("=" * 70)

    result = TestResult("Tushare Client")

    try:
        from app.data.tushare_client import get_tushare_client, TushareClient

        # 测试获取客户端
        client = get_tushare_client()
        result.add_pass("获取 Tushare Client 实例")

        # 测试单例模式
        client2 = get_tushare_client()
        if client is client2:
            result.add_pass("单例模式正确")
        else:
            result.add_fail("单例模式", "返回了不同的实例")

        # 测试缓存信息
        cache_info = client.get_cache_info()
        if isinstance(cache_info, dict) and 'total_cached' in cache_info:
            result.add_pass("获取缓存信息")
            print(f"     缓存: {cache_info['valid_cached']}/{cache_info['total_cached']}, TTL={cache_info['cache_ttl']}s")
        else:
            result.add_fail("缓存信息", "返回格式错误")

        # 测试股票代码标准化
        test_cases = [
            ("600519", "600519.SH"),
            ("000001", "000001.SZ"),
            ("sh600519", "600519.SH"),
            ("sz000001", "000001.SZ"),
            ("600519.SH", "600519.SH"),
        ]

        print("\n  股票代码标准化测试:")
        for input_code, expected in test_cases:
            try:
                normalized = client._normalize_stock_code(input_code)
                if normalized == expected:
                    result.add_pass(f"标准化 {input_code} -> {expected}")
                else:
                    result.add_fail(f"标准化 {input_code}", f"期望 {expected}，得到 {normalized}")
            except Exception as e:
                result.add_fail(f"标准化 {input_code}", str(e))

        # 检查 Token 配置
        if not client.token:
            result.add_skip("数据查询测试", "TUSHARE_API_TOKEN 未设置")
            print("\n  ⚠️  环境变量 TUSHARE_API_TOKEN 未设置，跳过数据查询测试")
        else:
            result.add_pass("TUSHARE_API_TOKEN 已配置")

            # 检测用户积分
            print("\n  用户积分检测:")
            user_points = client.get_user_points()
            if user_points is not None:
                result.add_pass(f"获取用户积分: {user_points}")
                print(f"     积分: {user_points}")
                if user_points < 200:
                    print(f"     ⚠️  积分不足 200，将跳过需要 daily 接口的测试")
            else:
                result.add_skip("积分检测", "无法获取积分信息")

            # 测试 get_stock_basic（低积分可用）
            print("\n  股票基本信息查询测试 (get_stock_basic):")
            basic_result = client.get_stock_basic("600519")
            if basic_result.get('success'):
                result.add_pass("查询 600519 基本信息")
                data = basic_result['data']
                print(f"     名称: {data.get('name')}")
                print(f"     代码: {data.get('ts_code')}")
                print(f"     行业: {data.get('industry')}")
                print(f"     地区: {data.get('area')}")
            else:
                result.add_fail("查询基本信息", basic_result.get('error'))

            # 测试查询股票数据
            print("\n  股票数据查询测试 (get_quote):")
            query_result = client.get_quote("600519")

            if query_result.get('success'):
                result.add_pass("查询 600519 (贵州茅台)")
                data = query_result['data']
                print(f"     名称: {data.get('name')}")
                print(f"     代码: {data.get('ts_code')}")

                # 检查是否为低积分模式
                if data.get('_low_points_mode'):
                    print(f"     模式: 低积分模式（仅基本信息）")
                    print(f"     行业: {data.get('industry', 'N/A')}")
                    print(f"     地区: {data.get('area', 'N/A')}")
                    result.add_pass("低积分模式数据获取")

                    # 验证低积分模式的字段
                    required_fields = ['name', 'ts_code']
                    missing_fields = [f for f in required_fields if f not in data]
                    if not missing_fields:
                        result.add_pass("低积分模式数据字段完整")
                    else:
                        result.add_fail("数据完整性", f"缺少字段: {missing_fields}")
                else:
                    print(f"     当前价: {data.get('nowPri')}")
                    print(f"     涨跌幅: {data.get('increPer')}%")

                    # 验证完整数据的字段
                    required_fields = ['name', 'nowPri', 'ts_code', 'increase', 'increPer',
                                      'todayStartPri', 'yestodEndPri', 'todayMax', 'todayMin']
                    missing_fields = [f for f in required_fields if f not in data or data[f] == 'N/A']
                    if not missing_fields:
                        result.add_pass("完整模式数据字段完整")
                    else:
                        result.add_fail("数据完整性", f"缺少字段: {missing_fields}")

                # 测试缓存
                print("\n  缓存机制测试:")
                cache_before = client.get_cache_info()['total_cached']
                query_result2 = client.get_quote("600519")  # 应该命中缓存
                cache_after = client.get_cache_info()['total_cached']

                if query_result2.get('success'):
                    result.add_pass("缓存查询")
                    if cache_after >= cache_before:
                        result.add_pass("缓存存储正常")
                        print(f"     缓存数: {cache_before} -> {cache_after}")
            else:
                error = query_result.get('error', 'Unknown error')
                if 'API 未初始化' in error:
                    result.add_skip("查询测试", "API Token 无效")
                else:
                    result.add_fail("查询 600519", error)

            # 测试无效股票代码
            print("\n  错误处理测试:")
            query_result = client.get_quote("999999")
            if not query_result.get('success'):
                result.add_pass("无效股票代码错误处理")
            else:
                result.add_fail("错误处理", "无效代码应返回失败")

    except Exception as e:
        result.add_fail("Tushare Client 测试", str(e))
        import traceback
        print(f"\n  详细错误:\n{traceback.format_exc()}")

    result.print_summary()
    return result.failed == 0


async def test_base_skill():
    """测试 Skill 基类"""
    print("\n" + "=" * 70)
    print("测试 2: BaseSkill (Skill 基类)")
    print("=" * 70)

    result = TestResult("BaseSkill")

    try:
        from app.mcp_server.skills.base import (
            BaseSkill, ToolDefinition, ToolParameter, ToolResult
        )

        # 测试 ToolParameter
        param = ToolParameter(
            name="test_param",
            type="string",
            description="测试参数",
            required=True
        )
        result.add_pass("创建 ToolParameter")

        # 测试 ToolDefinition
        tool_def = ToolDefinition(
            name="test_tool",
            description="测试工具",
            parameters=[param]
        )
        result.add_pass("创建 ToolDefinition")

        # 测试 JSON Schema 转换
        schema = tool_def.to_json_schema()
        if 'parameters' in schema and 'properties' in schema['parameters']:
            result.add_pass("JSON Schema 转换")
        else:
            result.add_fail("JSON Schema", "格式不正确")

        # 测试 ToolResult
        tool_result = ToolResult(success=True, data={"result": "ok"})
        result.add_pass("创建 ToolResult")

        result_dict = tool_result.to_dict()
        if result_dict.get('success') and result_dict.get('data'):
            result.add_pass("ToolResult.to_dict()")
        else:
            result.add_fail("ToolResult.to_dict()", "转换错误")

        # 创建测试 Skill
        class TestSkill(BaseSkill):
            name = "test"
            description = "测试 Skill"

            def _register_tools(self):
                self.register_tool(
                    name="echo",
                    handler=self.echo,
                    description="回显工具",
                    parameters=[
                        ToolParameter(name="message", type="string", description="消息", required=True)
                    ]
                )

            async def echo(self, message: str) -> ToolResult:
                return ToolResult(success=True, data={"echo": message})

        test_skill = TestSkill()
        result.add_pass("创建自定义 Skill")

        # 测试工具注册
        if test_skill.has_tool("echo"):
            result.add_pass("工具注册成功")
        else:
            result.add_fail("工具注册", "未找到工具")

        # 测试工具发现
        tools = test_skill.discover_tools()
        if len(tools) == 1 and tools[0].name == "echo":
            result.add_pass("工具发现")
        else:
            result.add_fail("工具发现", f"期望1个工具，实际 {len(tools)} 个")

        # 测试工具执行
        print("\n  工具执行测试:")
        exec_result = await test_skill.execute_tool("echo", {"message": "Hello"})
        if exec_result.success and exec_result.data.get("echo") == "Hello":
            result.add_pass("工具执行成功")
            print(f"     返回: {exec_result.data}")
        else:
            result.add_fail("工具执行", "返回数据不正确")

        # 测试参数验证
        print("\n  参数验证测试:")
        exec_result = await test_skill.execute_tool("echo", {})  # 缺少必填参数
        if not exec_result.success and "缺少必填参数" in exec_result.error:
            result.add_pass("必填参数检查")
        else:
            result.add_fail("参数验证", "未检测到缺少必填参数")

        # 测试不存在的工具
        exec_result = await test_skill.execute_tool("non_existent", {})
        if not exec_result.success:
            result.add_pass("不存在工具的错误处理")
        else:
            result.add_fail("工具存在性检查", "应该返回失败")

    except Exception as e:
        result.add_fail("BaseSkill 测试", str(e))
        import traceback
        print(f"\n  详细错误:\n{traceback.format_exc()}")

    result.print_summary()
    return result.failed == 0


async def test_market_data_skill():
    """测试 MarketData Skill"""
    print("\n" + "=" * 70)
    print("测试 3: MarketData Skill (市场数据 Skill)")
    print("=" * 70)

    result = TestResult("MarketData Skill")

    try:
        from app.mcp_server.skills.market_data import MarketDataSkill
        from app.mcp_server.skills.base import ToolResult
        from app.data.tushare_client import get_tushare_client

        # 创建 Skill
        skill = MarketDataSkill()
        result.add_pass("创建 MarketData Skill")

        # 测试属性
        if skill.name == "market_data":
            result.add_pass("Skill 名称正确")
        else:
            result.add_fail("Skill 名称", f"期望 'market_data'，得到 '{skill.name}'")

        # 测试工具注册
        tools = skill.discover_tools()
        print(f"\n  发现 {len(tools)} 个工具:")
        for tool in tools:
            print(f"    • {tool.name}: {tool.description[:60]}...")

        if len(tools) >= 2:
            result.add_pass(f"工具数量正确 ({len(tools)} 个)")
        else:
            result.add_fail("工具数量", f"期望至少2个，实际 {len(tools)} 个")

        tool_names = [t.name for t in tools]
        if "get_quote" in tool_names:
            result.add_pass("包含 get_quote 工具")
        else:
            result.add_fail("工具列表", "缺少 get_quote")

        if "search_stock" in tool_names:
            result.add_pass("包含 search_stock 工具")
        else:
            result.add_fail("工具列表", "缺少 search_stock")

        # 检查 Token 和积分
        token = os.getenv("TUSHARE_API_TOKEN")
        user_points = None
        if token:
            client = get_tushare_client()
            user_points = client.get_user_points()
            if user_points is not None:
                print(f"\n  用户积分: {user_points}")

        # 测试 get_quote 工具
        print("\n  get_quote 工具测试:")

        if not token:
            result.add_skip("get_quote 数据测试", "TUSHARE_API_TOKEN 未设置")
        else:
            # 测试正常查询
            exec_result = await skill.execute_tool("get_quote", {"symbol": "600519"})
            if exec_result.success:
                result.add_pass("查询 600519 成功")
                data = exec_result.data
                print(f"     {data.get('name')} ({data.get('ts_code')})")

                # 检查是否为低积分模式
                if data.get('_low_points_mode'):
                    print(f"     模式: 低积分模式")
                    print(f"     行业: {data.get('industry', 'N/A')}")
                    result.add_pass("低积分模式适配")
                else:
                    print(f"     价格: {data.get('nowPri')} | 涨跌: {data.get('increPer')}%")
            else:
                result.add_fail("查询 600519", exec_result.error)

            # 测试不同格式（仅在有积分时测试多个）
            if user_points is None or user_points >= 200:
                test_codes = [("000001", "平安银行"), ("sh600519", "带前缀")]
                for code, desc in test_codes:
                    exec_result = await skill.execute_tool("get_quote", {"symbol": code})
                    if exec_result.success:
                        result.add_pass(f"查询 {code} ({desc})")
                    else:
                        result.add_fail(f"查询 {code}", exec_result.error)
            else:
                result.add_skip("多股票查询测试", f"积分不足 ({user_points} < 200)")

        # 测试错误处理
        print("\n  错误处理测试:")
        exec_result = await skill.execute_tool("get_quote", {"symbol": ""})
        if not exec_result.success:
            result.add_pass("空代码错误处理")
        else:
            result.add_fail("错误处理", "空代码应该返回失败")

        # 测试 search_stock 工具
        print("\n  search_stock 工具测试:")
        if not token:
            result.add_skip("search_stock 测试", "TUSHARE_API_TOKEN 未设置")
        else:
            exec_result = await skill.execute_tool("search_stock", {"keyword": "600519"})
            if exec_result.success:
                result.add_pass("搜索 600519")
                data = exec_result.data
                print(f"     找到 {data.get('count')} 个结果")
            else:
                result.add_fail("搜索 600519", exec_result.error)

            # 测试不存在的股票
            exec_result = await skill.execute_tool("search_stock", {"keyword": "999999"})
            if not exec_result.success:
                result.add_pass("不存在股票的错误处理")

        # 测试缓存功能
        print("\n  缓存功能测试:")
        cache_info = skill.get_cache_info()
        if isinstance(cache_info, dict):
            result.add_pass("获取缓存信息")
            print(f"     缓存: {cache_info.get('valid_cached')}/{cache_info.get('total_cached')}")

    except Exception as e:
        result.add_fail("MarketData Skill 测试", str(e))
        import traceback
        print(f"\n  详细错误:\n{traceback.format_exc()}")

    result.print_summary()
    return result.failed == 0


async def test_config():
    """测试配置管理"""
    print("\n" + "=" * 70)
    print("测试 4: Config (配置管理)")
    print("=" * 70)

    result = TestResult("Config")

    try:
        from app.mcp_server.config import get_config, MCPServerConfig, reload_config

        # 测试获取配置
        config = get_config()
        result.add_pass("获取配置实例")

        # 测试配置属性
        if hasattr(config, 'server_name') and config.server_name:
            result.add_pass("配置包含 server_name")
            print(f"     Server Name: {config.server_name}")
        else:
            result.add_fail("配置属性", "缺少 server_name")

        if hasattr(config, 'server_version'):
            result.add_pass("配置包含 server_version")
            print(f"     Server Version: {config.server_version}")

        if hasattr(config, 'cache_ttl'):
            result.add_pass("配置包含 cache_ttl")
            print(f"     Cache TTL: {config.cache_ttl}s")

        # 测试环境变量读取
        token = config.tushare_api_token
        if token:
            result.add_pass("读取 TUSHARE_API_TOKEN")
            print(f"     Token: {token[:20]}...{token[-10:]}")
        else:
            result.add_skip("Token 读取", "TUSHARE_API_TOKEN 未设置")

        # 测试单例模式
        config2 = get_config()
        if config is config2:
            result.add_pass("配置单例模式")
        else:
            result.add_fail("单例模式", "返回了不同的实例")

        # 测试重新加载
        new_config = reload_config()
        if isinstance(new_config, MCPServerConfig):
            result.add_pass("重新加载配置")

    except Exception as e:
        result.add_fail("Config 测试", str(e))
        import traceback
        print(f"\n  详细错误:\n{traceback.format_exc()}")

    result.print_summary()
    return result.failed == 0


async def run_all_tests():
    """运行所有测试"""
    print("=" * 70)
    print("MCP Server 基础功能测试")
    print("=" * 70)
    print("测试范围: Skills + Data 层（不依赖 MCP SDK）")
    print(f"Python 版本: {sys.version.split()[0]}")

    token = os.getenv("TUSHARE_API_TOKEN")
    if token:
        print(f"✅ TUSHARE_API_TOKEN: 已设置")
    else:
        print("⚠️  TUSHARE_API_TOKEN: 未设置（部分测试将跳过）")
        print("   设置方法: export TUSHARE_API_TOKEN=your_token_here")

    print("=" * 70)

    all_results = []

    # 测试1: Tushare Client (数据层)
    passed = await test_tushare_client()
    all_results.append(("Tushare Client", passed))

    # 测试2: BaseSkill (Skill 基类)
    passed = await test_base_skill()
    all_results.append(("BaseSkill", passed))

    # 测试3: MarketData Skill
    passed = await test_market_data_skill()
    all_results.append(("MarketData Skill", passed))

    # 测试4: Config
    passed = await test_config()
    all_results.append(("Config", passed))

    # 最终总结
    print("\n" + "=" * 70)
    print("测试总结")
    print("=" * 70)

    total_passed = sum(1 for _, passed in all_results if passed)
    total_tests = len(all_results)

    for test_name, passed in all_results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{status} - {test_name}")

    print("=" * 70)
    print(f"总计: {total_passed}/{total_tests} 测试套件通过")

    if total_passed == total_tests:
        print("✅ 所有测试通过！")
        print("\n💡 提示: 要测试完整的 MCP Server，需要安装 mcp 包")
        print("   安装命令: pip install mcp")
    else:
        print("❌ 部分测试失败，请查看上面的详细信息")

    print("=" * 70)

    return total_passed == total_tests


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
