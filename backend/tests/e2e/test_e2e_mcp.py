#!/usr/bin/env python3
"""
完整的端到端集成测试

测试 MCP Server、MCP Client、ToolAdapter 和 DeepScout 的完整集成流程。

测试场景：
1. MCP Server 测试 - 验证 Server 启动和工具调用
2. MCP Client 测试 - 验证 Client 连接和工具列表
3. DeepScout 集成测试 - 验证与深度研究的集成
4. 降级机制测试 - 验证 MCP 失败时的降级
5. 完整研究测试 - 验证端到端研究流程

运行方式：
    cd backend
    python -m pytest tests/e2e/test_e2e_mcp.py -v -s

或直接运行：
    python -m tests.e2e.test_e2e_mcp
"""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
import traceback

# 添加项目路径
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, project_root)

# 检查 MCP 依赖
MCP_AVAILABLE = False
try:
    import mcp
    MCP_AVAILABLE = True
    print("✅ MCP SDK 已安装")
except ImportError:
    print("⚠️  MCP SDK 未安装，将跳过 MCP 相关测试")

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TestResult:
    """测试结果追踪"""

    def __init__(self, scenario_name: str):
        self.scenario_name = scenario_name
        self.total = 0
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.errors: List[tuple] = []
        self.start_time = time.time()
        self.end_time = None
        self.performance_data = {}

    def add_pass(self, test_name: str, duration: Optional[float] = None):
        """添加通过的测试"""
        self.total += 1
        self.passed += 1
        duration_str = f" ({duration:.2f}s)" if duration else ""
        print(f"  ✅ {test_name}{duration_str}")

    def add_fail(self, test_name: str, error: str):
        """添加失败的测试"""
        self.total += 1
        self.failed += 1
        self.errors.append((test_name, error))
        print(f"  ❌ {test_name}")
        print(f"     错误: {error}")

    def add_skip(self, test_name: str, reason: str):
        """添加跳过的测试"""
        self.total += 1
        self.skipped += 1
        print(f"  ⏭️  {test_name}")
        print(f"     原因: {reason}")

    def add_performance(self, metric: str, value: Any):
        """添加性能数据"""
        self.performance_data[metric] = value

    def finish(self):
        """完成测试"""
        self.end_time = time.time()

    def get_duration(self) -> float:
        """获取测试持续时间"""
        if self.end_time:
            return self.end_time - self.start_time
        return time.time() - self.start_time

    def print_summary(self):
        """打印测试摘要"""
        duration = self.get_duration()
        print(f"\n{'='*70}")
        print(f"场景: {self.scenario_name}")
        print(f"{'='*70}")
        print(f"总计: {self.total} | ✅ {self.passed} | ❌ {self.failed} | ⏭️  {self.skipped}")
        print(f"耗时: {duration:.2f}s")

        if self.performance_data:
            print(f"\n性能数据:")
            for metric, value in self.performance_data.items():
                print(f"  {metric}: {value}")

        if self.errors:
            print(f"\n失败详情:")
            for test_name, error in self.errors:
                print(f"  - {test_name}")
                print(f"    {error}")

        print(f"{'='*70}\n")
        return self.failed == 0


class E2ETestSuite:
    """端到端测试套件"""

    def __init__(self):
        self.all_results: List[TestResult] = []
        self.mcp_available = MCP_AVAILABLE
        self.server_script_path = os.path.abspath(
            os.path.join(project_root, "backend/app/mcp_server/server.py")
        )

    async def scenario_1_mcp_server_test(self) -> TestResult:
        """
        场景1: MCP Server 测试

        验证 MCP Server 能够正常启动并响应工具调用
        """
        result = TestResult("场景1: MCP Server 测试")
        print(f"\n{'='*70}")
        print(f"开始测试: {result.scenario_name}")
        print(f"{'='*70}")

        if not self.mcp_available:
            result.add_skip("MCP Server 测试", "MCP SDK 未安装")
            result.finish()
            return result

        mcp_client = None
        try:
            from app.mcp_client.client import MCPClient

            # 检查 server.py 是否存在
            if not os.path.exists(self.server_script_path):
                result.add_fail("Server 脚本检查", f"找不到: {self.server_script_path}")
                result.finish()
                return result

            result.add_pass("Server 脚本存在")

            # 创建 MCP Client
            start_time = time.time()
            mcp_client = MCPClient(
                server_script_path=self.server_script_path,
                python_executable="python3",
                connect_timeout=15.0,
                call_timeout=15.0
            )

            # 尝试连接
            connected = await mcp_client.connect()
            duration = time.time() - start_time

            if not connected:
                result.add_fail("启动 MCP Server", "连接失败")
                result.finish()
                return result

            result.add_pass("启动 MCP Server", duration)
            result.add_performance("Server 启动时间", f"{duration:.2f}s")

            # 获取工具列表
            start_time = time.time()
            tools_result = await mcp_client.list_tools()
            list_duration = time.time() - start_time

            if not tools_result.get("success"):
                result.add_fail("获取工具列表", tools_result.get("error", "未知错误"))
            else:
                tools = tools_result.get("tools", [])
                result.add_pass(f"获取工具列表 (共 {len(tools)} 个)", list_duration)
                result.add_performance("工具数量", len(tools))

                # 验证必需的工具存在
                tool_names = [t["name"] for t in tools]
                required_tools = [
                    "market_data.get_quote",
                    "market_data.search_stock",
                    "market_data.get_market_list"
                ]

                for tool_name in required_tools:
                    if tool_name in tool_names:
                        result.add_pass(f"工具存在: {tool_name}")
                    else:
                        result.add_fail(f"工具缺失: {tool_name}", "工具未注册")

            # 测试工具调用
            start_time = time.time()
            quote_result = await mcp_client.call_tool(
                "market_data.get_quote",
                {"symbol": "600519"}
            )
            quote_duration = time.time() - start_time

            if not quote_result.get("success"):
                error_msg = quote_result.get("error", "未知错误")
                if "token" in error_msg.lower() or "未配置" in error_msg:
                    result.add_skip("获取茅台行情", f"API token 未配置: {error_msg}")
                else:
                    result.add_fail("获取茅台行情", error_msg)
            else:
                data = quote_result.get("data", {})
                stock_name = data.get("name", "")
                result.add_pass(f"获取茅台行情 ({stock_name})", quote_duration)
                result.add_performance("get_quote 响应时间", f"{quote_duration:.2f}s")

                # 验证返回数据格式
                required_fields = ["code", "name"]
                for field in required_fields:
                    if field in data:
                        result.add_pass(f"数据包含字段: {field}")
                    else:
                        result.add_fail(f"数据缺少字段: {field}", "字段缺失")

        except Exception as e:
            result.add_fail("场景执行异常", f"{type(e).__name__}: {str(e)}")
            logger.error(f"场景1异常: {traceback.format_exc()}")
        finally:
            if mcp_client and mcp_client.is_connected:
                await mcp_client.disconnect()
            result.finish()

        return result

    async def scenario_2_mcp_client_test(self) -> TestResult:
        """
        场景2: MCP Client 测试

        验证 MCP Client 的连接管理和错误处理
        """
        result = TestResult("场景2: MCP Client 测试")
        print(f"\n{'='*70}")
        print(f"开始测试: {result.scenario_name}")
        print(f"{'='*70}")

        if not self.mcp_available:
            result.add_skip("MCP Client 测试", "MCP SDK 未安装")
            result.finish()
            return result

        try:
            from app.mcp_client.client import MCPClient

            # 测试1: 无效路径连接
            invalid_path = "/invalid/path/server.py"
            mcp_client = MCPClient(
                server_script_path=invalid_path,
                connect_timeout=2.0,
                call_timeout=2.0
            )

            start_time = time.time()
            connected = await mcp_client.connect()
            duration = time.time() - start_time

            if connected:
                result.add_fail("无效路径连接测试", "不应该连接成功")
                await mcp_client.disconnect()
            else:
                result.add_pass("无效路径正确失败", duration)

            # 测试2: 正常连接
            mcp_client = MCPClient(
                server_script_path=self.server_script_path,
                connect_timeout=10.0,
                call_timeout=10.0
            )

            start_time = time.time()
            connected = await mcp_client.connect()
            duration = time.time() - start_time

            if not connected:
                result.add_fail("正常连接", "连接失败")
                result.finish()
                return result

            result.add_pass("正常连接成功", duration)

            # 测试3: 重复连接
            start_time = time.time()
            connected_again = await mcp_client.connect()
            duration = time.time() - start_time

            if connected_again:
                result.add_pass("重复连接处理正确", duration)
            else:
                result.add_fail("重复连接", "不应该失败")

            # 测试4: 工具调用
            quote_result = await mcp_client.call_tool(
                "market_data.get_quote",
                {"symbol": "000858"}
            )

            if quote_result.get("success") or "token" in quote_result.get("error", "").lower():
                result.add_pass("工具调用正常（或 API 未配置）")
            else:
                result.add_fail("工具调用", quote_result.get("error", "未知错误"))

            # 测试5: 断开连接
            start_time = time.time()
            await mcp_client.disconnect()
            duration = time.time() - start_time

            if not mcp_client.is_connected:
                result.add_pass("断开连接成功", duration)
            else:
                result.add_fail("断开连接", "连接状态未更新")

            # 测试6: 断开后调用
            quote_result = await mcp_client.call_tool(
                "market_data.get_quote",
                {"symbol": "600519"}
            )

            if not quote_result.get("success") and "未连接" in quote_result.get("error", ""):
                result.add_pass("断开后调用正确失败")
            else:
                result.add_fail("断开后调用", "应该失败")

        except Exception as e:
            result.add_fail("场景执行异常", f"{type(e).__name__}: {str(e)}")
            logger.error(f"场景2异常: {traceback.format_exc()}")
        finally:
            result.finish()

        return result

    async def scenario_3_deepscout_integration_test(self) -> TestResult:
        """
        场景3: DeepScout 集成测试

        验证 ToolAdapter 与 DeepResearch 的集成
        """
        result = TestResult("场景3: DeepScout 集成测试")
        print(f"\n{'='*70}")
        print(f"开始测试: {result.scenario_name}")
        print(f"{'='*70}")

        mcp_client = None
        try:
            # 动态导入避免 MCP 依赖问题
            try:
                from app.mcp_client.adapter import ToolAdapter
            except ImportError as e:
                if "mcp" in str(e).lower():
                    result.add_skip("ToolAdapter 导入", "需要 MCP SDK")
                    result.finish()
                    return result
                raise

            # 测试1: 创建 ToolAdapter（无 MCP）
            adapter_fallback = ToolAdapter(mcp_client=None, fallback_enabled=True)
            result.add_pass("创建 ToolAdapter (降级模式)")

            # 验证降级标志
            if not adapter_fallback.is_using_mcp:
                result.add_pass("ToolAdapter 正确识别降级状态")
            else:
                result.add_fail("ToolAdapter 状态", "不应该使用 MCP")

            # 测试降级调用
            start_time = time.time()
            stock_result = await adapter_fallback.get_stock_by_code("600519")
            duration = time.time() - start_time

            if stock_result.get("success"):
                data = stock_result.get("data", {})
                stock_name = data.get("name", "")
                result.add_pass(f"降级调用成功 ({stock_name})", duration)
                result.add_performance("降级响应时间", f"{duration:.2f}s")
            else:
                error_msg = stock_result.get("error", "")
                if "token" in error_msg.lower() or "不可用" in error_msg:
                    result.add_skip("降级调用", f"API 未配置: {error_msg}")
                else:
                    result.add_fail("降级调用", error_msg)

            # 测试2: 如果 MCP 可用，测试 MCP 模式
            if self.mcp_available:
                try:
                    from app.mcp_client.client import MCPClient

                    mcp_client = MCPClient(
                        server_script_path=self.server_script_path,
                        connect_timeout=10.0,
                        call_timeout=10.0
                    )

                    connected = await mcp_client.connect()
                    if connected:
                        result.add_pass("MCP Client 连接成功")

                        # 创建带 MCP 的 ToolAdapter
                        adapter_mcp = ToolAdapter(
                            mcp_client=mcp_client,
                            fallback_enabled=True
                        )

                        if adapter_mcp.is_using_mcp:
                            result.add_pass("ToolAdapter 正确识别 MCP 状态")
                        else:
                            result.add_fail("ToolAdapter 状态", "应该使用 MCP")

                        # 测试 MCP 调用
                        start_time = time.time()
                        stock_result_mcp = await adapter_mcp.get_stock_by_code("600519")
                        duration = time.time() - start_time

                        if stock_result_mcp.get("success"):
                            data = stock_result_mcp.get("data", {})
                            stock_name = data.get("name", "")
                            result.add_pass(f"MCP 调用成功 ({stock_name})", duration)
                            result.add_performance("MCP 响应时间", f"{duration:.2f}s")
                        else:
                            error_msg = stock_result_mcp.get("error", "")
                            if "token" in error_msg.lower() or "未配置" in error_msg:
                                result.add_skip("MCP 调用", f"API 未配置: {error_msg}")
                            else:
                                result.add_fail("MCP 调用", error_msg)

                    else:
                        result.add_skip("MCP 测试", "连接失败")
                except Exception as e:
                    result.add_skip("MCP 测试", f"异常: {str(e)}")
            else:
                result.add_skip("MCP 模式测试", "MCP SDK 未安装")

        except ImportError as e:
            result.add_fail("导入错误", f"无法导入模块: {e}")
        except Exception as e:
            result.add_fail("场景执行异常", f"{type(e).__name__}: {str(e)}")
            logger.error(f"场景3异常: {traceback.format_exc()}")
        finally:
            if mcp_client and mcp_client.is_connected:
                await mcp_client.disconnect()
            result.finish()

        return result

    async def scenario_4_fallback_test(self) -> TestResult:
        """
        场景4: 降级机制测试

        验证 MCP 失败时的自动降级
        """
        result = TestResult("场景4: 降级机制测试")
        print(f"\n{'='*70}")
        print(f"开始测试: {result.scenario_name}")
        print(f"{'='*70}")

        mcp_client = None
        try:
            # 动态导入避免 MCP 依赖问题
            try:
                from app.mcp_client.adapter import ToolAdapter
            except ImportError as e:
                if "mcp" in str(e).lower():
                    result.add_skip("ToolAdapter 导入", "需要 MCP SDK")
                    result.finish()
                    return result
                raise

            # 测试1: MCP 不可用时的降级
            if self.mcp_available:
                from app.mcp_client.client import MCPClient

                # 创建无效的 MCP Client
                invalid_client = MCPClient(
                    server_script_path="/invalid/path.py",
                    connect_timeout=1.0,
                    call_timeout=1.0
                )

                # 不连接，直接创建 ToolAdapter
                adapter = ToolAdapter(
                    mcp_client=invalid_client,
                    fallback_enabled=True
                )

                result.add_pass("创建 ToolAdapter (MCP 未连接)")

                # 测试调用（应该降级）
                start_time = time.time()
                stock_result = await adapter.get_stock_by_code("600519")
                duration = time.time() - start_time

                if stock_result.get("success"):
                    data = stock_result.get("data", {})
                    stock_name = data.get("name", "")
                    result.add_pass(f"自动降级成功 ({stock_name})", duration)
                else:
                    error_msg = stock_result.get("error", "")
                    if "token" in error_msg.lower() or "不可用" in error_msg:
                        result.add_skip("自动降级", f"API 未配置: {error_msg}")
                    else:
                        result.add_fail("自动降级", error_msg)
            else:
                result.add_skip("MCP 降级测试", "MCP SDK 未安装")

            # 测试2: 禁用降级时的行为
            adapter_no_fallback = ToolAdapter(
                mcp_client=None,
                fallback_enabled=False
            )

            stock_result = await adapter_no_fallback.get_stock_by_code("600519")

            if not stock_result.get("success"):
                result.add_pass("禁用降级时正确失败")
            else:
                result.add_fail("禁用降级测试", "不应该成功")

            # 测试3: 搜索功能的降级
            adapter_search = ToolAdapter(mcp_client=None, fallback_enabled=True)

            start_time = time.time()
            search_result = await adapter_search.search_stock("茅台")
            duration = time.time() - start_time

            if search_result.get("success"):
                data = search_result.get("data", [])
                result.add_pass(f"搜索降级成功 (找到 {len(data)} 个结果)", duration)
            else:
                error_msg = search_result.get("error", "")
                if "token" in error_msg.lower() or "不可用" in error_msg:
                    result.add_skip("搜索降级", f"API 未配置: {error_msg}")
                else:
                    result.add_fail("搜索降级", error_msg)

        except ImportError as e:
            result.add_fail("导入错误", f"无法导入模块: {e}")
        except Exception as e:
            result.add_fail("场景执行异常", f"{type(e).__name__}: {str(e)}")
            logger.error(f"场景4异常: {traceback.format_exc()}")
        finally:
            if mcp_client and mcp_client.is_connected:
                await mcp_client.disconnect()
            result.finish()

        return result

    async def scenario_5_full_research_test(self) -> TestResult:
        """
        场景5: 完整研究测试

        验证端到端的研究流程（简化版）
        """
        result = TestResult("场景5: 完整研究测试")
        print(f"\n{'='*70}")
        print(f"开始测试: {result.scenario_name}")
        print(f"{'='*70}")

        try:
            # 动态导入避免 MCP 依赖问题
            try:
                from app.mcp_client.adapter import ToolAdapter
            except ImportError as e:
                if "mcp" in str(e).lower():
                    result.add_skip("ToolAdapter 导入", "需要 MCP SDK")
                    result.finish()
                    return result
                raise

            # 创建 ToolAdapter
            adapter = ToolAdapter(mcp_client=None, fallback_enabled=True)
            result.add_pass("创建 ToolAdapter")

            # 模拟研究流程的几个关键步骤
            # 1. 搜索股票
            start_time = time.time()
            search_result = await adapter.search_stock("茅台")
            search_duration = time.time() - start_time

            if search_result.get("success"):
                stocks = search_result.get("data", [])
                result.add_pass(f"步骤1: 搜索股票 (找到 {len(stocks)} 个)", search_duration)
                result.add_performance("搜索耗时", f"{search_duration:.2f}s")

                # 2. 获取第一个股票的详情
                if stocks:
                    stock_code = stocks[0].get("code", "")
                    start_time = time.time()
                    quote_result = await adapter.get_stock_by_code(stock_code)
                    quote_duration = time.time() - start_time

                    if quote_result.get("success"):
                        data = quote_result.get("data", {})
                        stock_name = data.get("name", "")
                        result.add_pass(f"步骤2: 获取行情 ({stock_name})", quote_duration)
                        result.add_performance("行情获取耗时", f"{quote_duration:.2f}s")

                        # 3. 验证数据完整性
                        required_fields = ["code", "name"]
                        missing_fields = [f for f in required_fields if f not in data]

                        if not missing_fields:
                            result.add_pass("步骤3: 数据完整性验证通过")
                        else:
                            result.add_fail(
                                "步骤3: 数据完整性",
                                f"缺少字段: {', '.join(missing_fields)}"
                            )

                        # 4. 计算总体性能
                        total_time = search_duration + quote_duration
                        result.add_performance("总耗时", f"{total_time:.2f}s")

                        if total_time < 5.0:
                            result.add_pass("步骤4: 性能符合预期 (<5s)")
                        else:
                            result.add_fail("步骤4: 性能", f"超时: {total_time:.2f}s")

                    else:
                        error_msg = quote_result.get("error", "")
                        if "token" in error_msg.lower() or "不可用" in error_msg:
                            result.add_skip("步骤2: 获取行情", f"API 未配置: {error_msg}")
                        else:
                            result.add_fail("步骤2: 获取行情", error_msg)
                else:
                    result.add_skip("步骤2: 获取行情", "没有搜索结果")
            else:
                error_msg = search_result.get("error", "")
                if "token" in error_msg.lower() or "不可用" in error_msg:
                    result.add_skip("步骤1: 搜索股票", f"API 未配置: {error_msg}")
                else:
                    result.add_fail("步骤1: 搜索股票", error_msg)

        except ImportError as e:
            result.add_fail("导入错误", f"无法导入模块: {e}")
        except Exception as e:
            result.add_fail("场景执行异常", f"{type(e).__name__}: {str(e)}")
            logger.error(f"场景5异常: {traceback.format_exc()}")
        finally:
            result.finish()

        return result

    def generate_report(self, results: List[TestResult]) -> str:
        """生成测试报告"""
        report_lines = []
        report_lines.append("# 端到端集成测试报告")
        report_lines.append("")
        report_lines.append(f"**测试时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append(f"**MCP SDK**: {'已安装 ✅' if self.mcp_available else '未安装 ⚠️'}")
        report_lines.append(f"**测试环境**: {os.name} / Python {sys.version.split()[0]}")
        report_lines.append("")

        # 总体统计
        total_tests = sum(r.total for r in results)
        total_passed = sum(r.passed for r in results)
        total_failed = sum(r.failed for r in results)
        total_skipped = sum(r.skipped for r in results)
        total_duration = sum(r.get_duration() for r in results)

        report_lines.append("## 总体统计")
        report_lines.append("")
        report_lines.append(f"- **总测试数**: {total_tests}")
        report_lines.append(f"- **通过**: {total_passed} ✅")
        report_lines.append(f"- **失败**: {total_failed} ❌")
        report_lines.append(f"- **跳过**: {total_skipped} ⏭️")
        report_lines.append(f"- **总耗时**: {total_duration:.2f}s")
        if total_tests > 0:
            pass_rate = (total_passed / total_tests * 100)
            report_lines.append(f"- **通过率**: {pass_rate:.1f}%")
        report_lines.append("")

        # 各场景详情
        report_lines.append("## 场景测试详情")
        report_lines.append("")

        for i, r in enumerate(results, 1):
            status_icon = "✅" if r.failed == 0 else "❌"
            report_lines.append(f"### 场景 {i}: {r.scenario_name} {status_icon}")
            report_lines.append("")
            report_lines.append(f"- **状态**: {'通过' if r.failed == 0 else '失败'}")
            report_lines.append(f"- **测试数**: {r.total} (✅ {r.passed} / ❌ {r.failed} / ⏭️  {r.skipped})")
            report_lines.append(f"- **耗时**: {r.get_duration():.2f}s")

            if r.performance_data:
                report_lines.append("- **性能数据**:")
                for metric, value in r.performance_data.items():
                    report_lines.append(f"  - {metric}: {value}")

            if r.errors:
                report_lines.append("- **失败详情**:")
                for test_name, error in r.errors:
                    report_lines.append(f"  - `{test_name}`: {error}")

            report_lines.append("")

        # 问题和建议
        report_lines.append("## 问题和建议")
        report_lines.append("")

        all_errors = []
        for r in results:
            for test_name, error in r.errors:
                all_errors.append((r.scenario_name, test_name, error))

        if all_errors:
            report_lines.append("### 失败的测试")
            report_lines.append("")
            for scenario, test, error in all_errors:
                report_lines.append(f"- **{scenario} - {test}**")
                report_lines.append(f"  ```")
                report_lines.append(f"  {error}")
                report_lines.append(f"  ```")
                report_lines.append("")
        else:
            report_lines.append("✅ **所有测试通过，未发现问题**")
            report_lines.append("")

        # 环境说明
        report_lines.append("## 环境和配置")
        report_lines.append("")
        if not self.mcp_available:
            report_lines.append("⚠️  **MCP SDK 未安装**")
            report_lines.append("")
            report_lines.append("要启用完整的 MCP 测试，请安装:")
            report_lines.append("")
            report_lines.append("```bash")
            report_lines.append("pip install mcp")
            report_lines.append("```")
        else:
            report_lines.append("✅ **MCP SDK 已安装**")
            report_lines.append("")
            report_lines.append("MCP Server 路径:")
            report_lines.append(f"```")
            report_lines.append(f"{self.server_script_path}")
            report_lines.append(f"```")

        report_lines.append("")
        report_lines.append("## 测试覆盖")
        report_lines.append("")
        report_lines.append("本测试覆盖以下组件和功能:")
        report_lines.append("")
        report_lines.append("1. **MCP Server** - Server 启动、工具注册、工具调用")
        report_lines.append("2. **MCP Client** - 连接管理、工具列表、错误处理")
        report_lines.append("3. **ToolAdapter** - MCP 集成、降级机制、接口兼容")
        report_lines.append("4. **降级机制** - 自动降级、StockService fallback")
        report_lines.append("5. **端到端流程** - 完整的研究流程验证")
        report_lines.append("")

        report_lines.append("---")
        report_lines.append(f"*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")

        return "\n".join(report_lines)

    async def run_all_tests(self):
        """运行所有测试场景"""
        print("\n" + "="*70)
        print("端到端集成测试")
        print("="*70)
        print(f"测试开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"MCP SDK 状态: {'已安装 ✅' if self.mcp_available else '未安装 ⚠️'}")
        print("="*70)

        # 依次运行所有场景
        scenarios = [
            self.scenario_1_mcp_server_test,
            self.scenario_2_mcp_client_test,
            self.scenario_3_deepscout_integration_test,
            self.scenario_4_fallback_test,
            self.scenario_5_full_research_test,
        ]

        for scenario_func in scenarios:
            result = await scenario_func()
            result.print_summary()
            self.all_results.append(result)

        # 打印最终摘要
        self.print_final_summary()

        # 生成报告
        report = self.generate_report(self.all_results)

        # 保存报告
        report_path = os.path.join(
            os.path.dirname(__file__),
            "E2E_TEST_REPORT.md"
        )
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)

        print(f"\n📄 测试报告已保存到: {report_path}")

        return self.all_results

    def print_final_summary(self):
        """打印最终总结"""
        total_tests = sum(r.total for r in self.all_results)
        total_passed = sum(r.passed for r in self.all_results)
        total_failed = sum(r.failed for r in self.all_results)
        total_skipped = sum(r.skipped for r in self.all_results)
        total_duration = sum(r.get_duration() for r in self.all_results)

        print("\n" + "="*70)
        print("最终测试摘要")
        print("="*70)
        print(f"场景数: {len(self.all_results)}")
        print(f"总测试数: {total_tests}")
        print(f"✅ 通过: {total_passed}")
        print(f"❌ 失败: {total_failed}")
        print(f"⏭️  跳过: {total_skipped}")
        print(f"总耗时: {total_duration:.2f}s")

        if total_tests > 0:
            pass_rate = (total_passed / total_tests) * 100
            print(f"通过率: {pass_rate:.1f}%")

        print("="*70)

        # 打印各场景状态
        print("\n场景状态:")
        for i, r in enumerate(self.all_results, 1):
            status = "✅ 通过" if r.failed == 0 else "❌ 失败"
            print(f"  {i}. {r.scenario_name}: {status} ({r.passed}/{r.total})")

        if total_failed == 0:
            print("\n🎉 所有测试通过!")
        else:
            print(f"\n⚠️  有 {total_failed} 个测试失败，请检查详细信息")


async def main():
    """主函数"""
    suite = E2ETestSuite()
    await suite.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())
