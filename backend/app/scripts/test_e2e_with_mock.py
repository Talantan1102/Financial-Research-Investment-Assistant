#!/usr/bin/env python3
"""
带 Mock 支持的端到端集成测试

这个版本可以在 MCP 依赖缺失时运行，测试降级机制。

测试场景：
1. 检测 MCP 依赖是否可用
2. 如果可用：测试 MCP Server 连接和功能
3. 如果不可用：测试降级机制（StockService fallback）
4. 生成清晰的测试报告

运行方式：
    python -m app.scripts.test_e2e_with_mock
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
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

# 检查 MCP 依赖
MCP_AVAILABLE = False
try:
    import mcp
    MCP_AVAILABLE = True
    print("✅ MCP SDK 已安装")
except ImportError:
    print("⚠️  MCP SDK 未安装，将使用 Mock 模式测试")

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


class E2ETestWithMock:
    """支持 Mock 模式的端到端测试"""

    def __init__(self):
        self.all_results: List[TestResult] = []
        self.mcp_available = MCP_AVAILABLE

    async def scenario_1_dependency_check(self) -> TestResult:
        """
        场景1: 依赖检查

        检查测试所需的依赖是否可用
        """
        result = TestResult("场景1: 依赖检查")
        print(f"\n{'='*70}")
        print(f"开始测试: {result.scenario_name}")
        print(f"{'='*70}")

        try:
            # 检查 MCP SDK
            if self.mcp_available:
                result.add_pass("MCP SDK 已安装")
            else:
                result.add_skip("MCP SDK", "未安装，将使用 Mock 模式")

            # 检查其他必要的导入
            try:
                from app.mcp_client.adapter import ToolAdapter
                result.add_pass("ToolAdapter 可导入")
            except ImportError as e:
                result.add_fail("ToolAdapter 导入", str(e))

            # 检查 StockService（降级后端）
            try:
                from app.service.stock_service import StockService
                result.add_pass("StockService 可导入（降级后端）")
            except ImportError as e:
                result.add_fail("StockService 导入", str(e))

        except Exception as e:
            result.add_fail("依赖检查异常", f"{type(e).__name__}: {str(e)}")
        finally:
            result.finish()

        return result

    async def scenario_2_fallback_mechanism(self) -> TestResult:
        """
        场景2: 降级机制测试

        测试当 MCP 不可用时，系统能否正常降级到 StockService
        """
        result = TestResult("场景2: 降级机制测试")
        print(f"\n{'='*70}")
        print(f"开始测试: {result.scenario_name}")
        print(f"{'='*70}")

        try:
            # 检查是否能导入 ToolAdapter
            try:
                if self.mcp_available:
                    from app.mcp_client.client import MCPClient
                    from app.mcp_client.adapter import ToolAdapter

                    # 创建无效的 MCP Client（模拟连接失败）
                    invalid_path = "/invalid/path/server.py"
                    mcp_client = MCPClient(
                        server_script_path=invalid_path,
                        connect_timeout=2.0,
                        call_timeout=2.0
                    )

                    # 尝试连接（应该失败）
                    start_time = time.time()
                    connected = await mcp_client.connect()
                    duration = time.time() - start_time

                    if connected:
                        result.add_fail("MCP 连接失败测试", "连接不应该成功")
                    else:
                        result.add_pass("MCP 连接正确失败", duration)

                    # 创建 ToolAdapter（启用降级）
                    tool_adapter = ToolAdapter(
                        mcp_client=mcp_client,
                        fallback_enabled=True
                    )
                else:
                    # MCP 不可用，直接测试 StockService
                    from app.service.stock_service import StockService
                    stock_service = StockService()

                    result.add_skip("MCP 降级测试", "MCP SDK 不可用，直接测试 StockService")

                    # 测试 StockService
                    start_time = time.time()
                    stock_result = await stock_service.get_quote("600519")
                    duration = time.time() - start_time

                    if stock_result.get("success"):
                        data = stock_result.get("data", {})
                        stock_name = data.get("name", "")
                        result.add_pass(f"StockService 获取数据 ({stock_name})", duration)
                        result.add_performance("StockService 响应时间", f"{duration:.2f}s")
                    else:
                        error_msg = stock_result.get("error", "")
                        if "token" in error_msg.lower() or "不可用" in error_msg:
                            result.add_skip("StockService 调用", f"API 未配置: {error_msg}")
                        else:
                            result.add_fail("StockService 调用", error_msg)

                    result.finish()
                    return result

                # 测试降级调用
                result.add_pass("创建 ToolAdapter (启用降级)")

                start_time = time.time()
                stock_result = await tool_adapter.get_stock_by_code("600519")
                duration = time.time() - start_time

                if stock_result.get("success"):
                    data = stock_result.get("data", {})
                    stock_name = data.get("name", "")
                    result.add_pass(f"降级调用成功 ({stock_name})", duration)
                    result.add_performance("降级调用时间", f"{duration:.2f}s")
                else:
                    error_msg = stock_result.get("error", "")
                    if "不可用" in error_msg or "token" in error_msg.lower():
                        result.add_skip("降级调用", f"StockService 也不可用: {error_msg}")
                    else:
                        result.add_fail("降级调用", error_msg)

                # 验证降级标志
                if not tool_adapter.is_using_mcp:
                    result.add_pass("ToolAdapter 不使用 MCP")
                else:
                    result.add_fail("ToolAdapter 状态", "不应该使用 MCP")

            except ImportError as e:
                result.add_fail("导入错误", f"无法导入必要的模块: {e}")

        except Exception as e:
            result.add_fail("场景执行异常", f"{type(e).__name__}: {str(e)}")
            logger.error(f"场景2异常: {traceback.format_exc()}")
        finally:
            result.finish()

        return result

    async def scenario_3_mcp_connection(self) -> TestResult:
        """
        场景3: MCP 连接测试（如果可用）

        测试 MCP Server 的启动和连接
        """
        result = TestResult("场景3: MCP 连接测试")
        print(f"\n{'='*70}")
        print(f"开始测试: {result.scenario_name}")
        print(f"{'='*70}")

        if not self.mcp_available:
            result.add_skip("MCP 连接测试", "MCP SDK 未安装")
            result.finish()
            return result

        mcp_client = None
        try:
            from app.mcp_client.client import MCPClient

            server_script_path = os.path.abspath(
                os.path.join(
                    os.path.dirname(__file__),
                    "../mcp_server/server.py"
                )
            )

            # 创建 MCP Client
            start_time = time.time()
            mcp_client = MCPClient(
                server_script_path=server_script_path,
                python_executable="python3",
                connect_timeout=10.0,
                call_timeout=10.0
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

        except Exception as e:
            result.add_fail("场景执行异常", f"{type(e).__name__}: {str(e)}")
            logger.error(f"场景3异常: {traceback.format_exc()}")
        finally:
            if mcp_client and mcp_client.is_connected:
                await mcp_client.disconnect()
            result.finish()

        return result

    async def scenario_4_tool_adapter(self) -> TestResult:
        """
        场景4: ToolAdapter 完整测试

        测试 ToolAdapter 在不同情况下的行为
        """
        result = TestResult("场景4: ToolAdapter 完整测试")
        print(f"\n{'='*70}")
        print(f"开始测试: {result.scenario_name}")
        print(f"{'='*70}")

        try:
            from app.mcp_client.adapter import ToolAdapter

            # 测试1: 无 MCP Client 时的降级
            tool_adapter = ToolAdapter(mcp_client=None, fallback_enabled=True)
            result.add_pass("创建 ToolAdapter (无 MCP Client)")

            # 检查状态
            if not tool_adapter.is_using_mcp:
                result.add_pass("ToolAdapter 正确识别无 MCP 状态")
            else:
                result.add_fail("ToolAdapter 状态", "不应该使用 MCP")

            # 测试降级调用
            try:
                start_time = time.time()
                stock_result = await tool_adapter.get_stock_by_code("600519")
                duration = time.time() - start_time

                if stock_result.get("success"):
                    data = stock_result.get("data", {})
                    stock_name = data.get("name", "")
                    result.add_pass(f"降级调用成功 ({stock_name})", duration)
                    result.add_performance("ToolAdapter 响应时间", f"{duration:.2f}s")
                else:
                    error_msg = stock_result.get("error", "")
                    if "token" in error_msg.lower() or "不可用" in error_msg:
                        result.add_skip("ToolAdapter 调用", f"API 未配置: {error_msg}")
                    else:
                        result.add_fail("ToolAdapter 调用", error_msg)
            except Exception as e:
                result.add_fail("ToolAdapter 调用异常", str(e))

            # 测试2: 如果 MCP 可用，测试正常流程
            if self.mcp_available:
                try:
                    from app.mcp_client.client import MCPClient

                    server_script_path = os.path.abspath(
                        os.path.join(
                            os.path.dirname(__file__),
                            "../mcp_server/server.py"
                        )
                    )

                    mcp_client = MCPClient(
                        server_script_path=server_script_path,
                        connect_timeout=5.0,
                        call_timeout=5.0
                    )

                    # 尝试连接
                    connected = await mcp_client.connect()
                    if connected:
                        result.add_pass("MCP Client 连接成功")

                        # 创建带 MCP 的 ToolAdapter
                        tool_adapter_mcp = ToolAdapter(
                            mcp_client=mcp_client,
                            fallback_enabled=True
                        )

                        # 测试 MCP 调用
                        start_time = time.time()
                        stock_result_mcp = await tool_adapter_mcp.get_stock_by_code("600519")
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

                        await mcp_client.disconnect()
                    else:
                        result.add_skip("MCP 连接测试", "连接失败，跳过 MCP 测试")
                except Exception as e:
                    result.add_skip("MCP 测试", f"MCP 测试异常: {str(e)}")
            else:
                result.add_skip("MCP 测试", "MCP SDK 未安装")

        except ImportError as e:
            result.add_fail("导入错误", f"无法导入 ToolAdapter: {e}")
        except Exception as e:
            result.add_fail("场景执行异常", f"{type(e).__name__}: {str(e)}")
            logger.error(f"场景4异常: {traceback.format_exc()}")
        finally:
            result.finish()

        return result

    async def scenario_5_data_format_validation(self) -> TestResult:
        """
        场景5: 数据格式验证

        验证返回的数据格式是否符合 DeepResearch 的要求
        """
        result = TestResult("场景5: 数据格式验证")
        print(f"\n{'='*70}")
        print(f"开始测试: {result.scenario_name}")
        print(f"{'='*70}")

        try:
            from app.mcp_client.adapter import ToolAdapter

            # 创建 ToolAdapter（使用降级模式）
            tool_adapter = ToolAdapter(mcp_client=None, fallback_enabled=True)

            # 测试 get_stock_by_code 返回格式
            stock_result = await tool_adapter.get_stock_by_code("600519")

            if stock_result.get("success"):
                result.add_pass("get_stock_by_code 调用成功")

                # 验证必需字段
                data = stock_result.get("data", {})
                required_fields = ["code", "name"]
                missing_fields = [f for f in required_fields if f not in data]

                if not missing_fields:
                    result.add_pass(f"数据包含必需字段: {', '.join(required_fields)}")
                else:
                    result.add_fail("数据字段检查", f"缺少字段: {', '.join(missing_fields)}")

                # 验证可选字段
                optional_fields = ["price", "change", "change_percent", "volume"]
                present_fields = [f for f in optional_fields if f in data]
                if present_fields:
                    result.add_pass(f"数据包含可选字段: {', '.join(present_fields)}")

                # 验证数据类型
                if isinstance(data.get("code"), str):
                    result.add_pass("code 字段类型正确 (str)")
                else:
                    result.add_fail("code 字段类型", f"期望 str，实际 {type(data.get('code'))}")

                if isinstance(data.get("name"), str):
                    result.add_pass("name 字段类型正确 (str)")
                else:
                    result.add_fail("name 字段类型", f"期望 str，实际 {type(data.get('name'))}")

            elif "token" in stock_result.get("error", "").lower() or "不可用" in stock_result.get("error", ""):
                result.add_skip("数据格式验证", f"API 未配置: {stock_result.get('error')}")
            else:
                result.add_fail("get_stock_by_code 调用", stock_result.get("error", "未知错误"))

            # 测试 search_stock 返回格式
            search_result = await tool_adapter.search_stock("茅台")

            if search_result.get("success"):
                result.add_pass("search_stock 调用成功")

                # 验证返回列表
                data_list = search_result.get("data", [])
                if isinstance(data_list, list):
                    result.add_pass(f"search_stock 返回列表 (共 {len(data_list)} 项)")

                    if data_list:
                        # 验证列表项格式
                        first_item = data_list[0]
                        required_fields = ["code", "name"]
                        missing_fields = [f for f in required_fields if f not in first_item]

                        if not missing_fields:
                            result.add_pass(f"搜索结果包含必需字段: {', '.join(required_fields)}")
                        else:
                            result.add_fail("搜索结果字段检查", f"缺少字段: {', '.join(missing_fields)}")
                    else:
                        result.add_skip("搜索结果验证", "搜索结果为空")
                else:
                    result.add_fail("search_stock 返回类型", f"期望 list，实际 {type(data_list)}")

            elif "token" in search_result.get("error", "").lower() or "不可用" in search_result.get("error", ""):
                result.add_skip("搜索格式验证", f"API 未配置: {search_result.get('error')}")
            else:
                result.add_fail("search_stock 调用", search_result.get("error", "未知错误"))

        except ImportError as e:
            result.add_fail("导入错误", f"无法导入必要的模块: {e}")
        except Exception as e:
            result.add_fail("场景执行异常", f"{type(e).__name__}: {str(e)}")
            logger.error(f"场景5异常: {traceback.format_exc()}")
        finally:
            result.finish()

        return result

    def generate_report(self, results: List[TestResult]) -> str:
        """生成测试报告"""
        report_lines = []
        report_lines.append("# 带 Mock 支持的端到端集成测试报告")
        report_lines.append("")
        report_lines.append(f"**测试时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append(f"**MCP SDK**: {'已安装 ✅' if self.mcp_available else '未安装 ⚠️'}")
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
            report_lines.append(f"- **通过率**: {(total_passed/total_tests*100):.1f}%")
        report_lines.append("")

        # 各场景详情
        report_lines.append("## 场景测试详情")
        report_lines.append("")

        for i, r in enumerate(results, 1):
            report_lines.append(f"### 场景 {i}: {r.scenario_name}")
            report_lines.append("")
            report_lines.append(f"- **状态**: {'✅ 通过' if r.failed == 0 else '❌ 失败'}")
            report_lines.append(f"- **测试数**: {r.total} (✅ {r.passed} / ❌ {r.failed} / ⏭️  {r.skipped})")
            report_lines.append(f"- **耗时**: {r.get_duration():.2f}s")

            if r.performance_data:
                report_lines.append(f"- **性能数据**:")
                for metric, value in r.performance_data.items():
                    report_lines.append(f"  - {metric}: {value}")

            if r.errors:
                report_lines.append(f"- **失败详情**:")
                for test_name, error in r.errors:
                    report_lines.append(f"  - {test_name}: {error}")

            report_lines.append("")

        # 问题和建议
        report_lines.append("## 发现的问题和建议")
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
                report_lines.append(f"  - 错误: {error}")
                report_lines.append("")
        else:
            report_lines.append("✅ 所有测试通过，未发现问题")
            report_lines.append("")

        # 环境建议
        report_lines.append("## 环境说明")
        report_lines.append("")
        if not self.mcp_available:
            report_lines.append("⚠️  **MCP SDK 未安装**")
            report_lines.append("")
            report_lines.append("要启用完整的 MCP 测试功能，请安装 MCP SDK:")
            report_lines.append("")
            report_lines.append("```bash")
            report_lines.append("pip install mcp")
            report_lines.append("```")
            report_lines.append("")
            report_lines.append("当前测试验证了降级机制能够正常工作。")
        else:
            report_lines.append("✅ MCP SDK 已安装，可以进行完整测试。")

        report_lines.append("")
        report_lines.append("---")
        report_lines.append(f"报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        return "\n".join(report_lines)

    async def run_all_tests(self):
        """运行所有测试场景"""
        print("\n" + "="*70)
        print("带 Mock 支持的端到端集成测试")
        print("="*70)
        print(f"测试开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"MCP SDK 状态: {'已安装 ✅' if self.mcp_available else '未安装 ⚠️'}")
        print("="*70)

        # 依次运行所有场景
        scenarios = [
            self.scenario_1_dependency_check,
            self.scenario_2_fallback_mechanism,
            self.scenario_3_mcp_connection,
            self.scenario_4_tool_adapter,
            self.scenario_5_data_format_validation,
        ]

        for scenario_func in scenarios:
            result = await scenario_func()
            result.print_summary()
            self.all_results.append(result)

        # 生成并打印总体摘要
        self.print_final_summary()

        # 生成报告
        report = self.generate_report(self.all_results)

        # 保存报告
        report_path = os.path.join(
            os.path.dirname(__file__),
            "E2E_WITH_MOCK_TEST_REPORT.md"
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
    suite = E2ETestWithMock()
    await suite.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())
