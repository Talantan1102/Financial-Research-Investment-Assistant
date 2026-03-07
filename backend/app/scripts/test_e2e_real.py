#!/usr/bin/env python3
"""
真实环境端到端集成测试
使用真实 TUSHARE_API_TOKEN 执行完整测试

环境要求：
    export TUSHARE_API_TOKEN="5a05084f5dbb829c251ffa1a15061529ba56a96c9988b5100057bed8"

测试场景：
1. 真实股票数据获取 (get_quote)
2. 股票搜索功能 (search_stock)
3. MCP Client 真实调用
4. 完整链路测试 (ToolAdapter)

运行方式：
    export TUSHARE_API_TOKEN="5a05084f5dbb829c251ffa1a15061529ba56a96c9988b5100057bed8"
    python -m app.scripts.test_e2e_real
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

from app.mcp_client.client import MCPClient
from app.mcp_client.adapter import ToolAdapter

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PerformanceMetrics:
    """性能指标收集器"""

    def __init__(self):
        self.metrics: List[Dict[str, Any]] = []

    def record(self, operation: str, duration: float, success: bool, details: str = ""):
        """记录性能指标"""
        self.metrics.append({
            "operation": operation,
            "duration_ms": round(duration * 1000, 2),
            "duration_s": round(duration, 2),
            "success": success,
            "details": details,
            "timestamp": datetime.now().isoformat()
        })

    def get_summary(self) -> Dict[str, Any]:
        """获取性能摘要"""
        if not self.metrics:
            return {}

        durations = [m["duration_ms"] for m in self.metrics]
        successes = [m for m in self.metrics if m["success"]]
        failures = [m for m in self.metrics if not m["success"]]

        return {
            "total_operations": len(self.metrics),
            "successful": len(successes),
            "failed": len(failures),
            "avg_duration_ms": round(sum(durations) / len(durations), 2),
            "min_duration_ms": min(durations),
            "max_duration_ms": max(durations),
            "total_duration_s": round(sum(m["duration_s"] for m in self.metrics), 2)
        }

    def print_details(self):
        """打印详细性能数据"""
        print("\n📊 性能数据详情:")
        print("-" * 80)
        for i, m in enumerate(self.metrics, 1):
            status = "✅" if m["success"] else "❌"
            print(f"{i}. {status} {m['operation']}: {m['duration_ms']}ms")
            if m["details"]:
                print(f"   {m['details']}")
        print("-" * 80)


class RealE2ETest:
    """真实环境端到端测试"""

    def __init__(self):
        self.server_script_path = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "../mcp_server/server.py"
            )
        )
        self.performance = PerformanceMetrics()
        self.test_results = {
            "passed": 0,
            "failed": 0,
            "errors": []
        }

    def check_environment(self) -> bool:
        """检查环境变量"""
        print("\n🔍 检查环境配置...")
        print("-" * 80)

        token = os.getenv("TUSHARE_API_TOKEN")
        if not token:
            print("❌ 未设置 TUSHARE_API_TOKEN 环境变量")
            print("   请设置: export TUSHARE_API_TOKEN='your_token_here'")
            return False

        # 显示 Token 的前后几位（隐藏中间部分）
        masked_token = f"{token[:8]}...{token[-8:]}" if len(token) > 16 else "***"
        print(f"✅ TUSHARE_API_TOKEN: {masked_token}")
        print(f"✅ MCP Server 路径: {self.server_script_path}")
        print("-" * 80)
        return True

    async def scenario_1_real_stock_data(self) -> bool:
        """
        场景1: 真实股票数据获取

        测试内容:
        - 获取贵州茅台 (600519) 实时行情
        - 获取平安银行 (000001) 实时行情
        - 验证返回字段完整性
        - 记录 API 响应时间
        """
        print("\n" + "="*80)
        print("场景1: 真实股票数据获取")
        print("="*80)

        mcp_client = None
        try:
            # 启动 MCP Server
            start_time = time.time()
            mcp_client = MCPClient(
                server_script_path=self.server_script_path,
                connect_timeout=15.0,
                call_timeout=15.0
            )

            connected = await mcp_client.connect()
            connect_duration = time.time() - start_time
            self.performance.record("MCP Server 启动", connect_duration, connected)

            if not connected:
                print("❌ MCP Server 启动失败")
                self.test_results["failed"] += 1
                self.test_results["errors"].append("MCP Server 启动失败")
                return False

            print(f"✅ MCP Server 启动成功 ({connect_duration:.2f}s)")
            self.test_results["passed"] += 1

            # 测试股票列表
            test_stocks = [
                {"code": "600519", "name": "贵州茅台", "expected_name": "贵州茅台"},
                {"code": "000001", "name": "平安银行", "expected_name": "平安银行"},
                {"code": "000858", "name": "五粮液", "expected_name": "五粮液"},
            ]

            for stock in test_stocks:
                print(f"\n📈 测试股票: {stock['name']} ({stock['code']})")

                # 调用 get_quote
                start_time = time.time()
                result = await mcp_client.call_tool(
                    "market_data.get_quote",
                    {"symbol": stock["code"]}
                )
                duration = time.time() - start_time

                success = result.get("success", False)
                self.performance.record(
                    f"get_quote({stock['code']})",
                    duration,
                    success,
                    f"股票: {stock['name']}"
                )

                if not success:
                    error = result.get("error", "未知错误")
                    print(f"❌ 获取失败: {error}")
                    self.test_results["failed"] += 1
                    self.test_results["errors"].append(f"{stock['name']}: {error}")
                    continue

                # 验证数据
                data = result.get("data", {})
                required_fields = ["name", "nowPri", "increase", "increPer"]
                missing_fields = [f for f in required_fields if f not in data]

                if missing_fields:
                    print(f"❌ 数据不完整，缺少字段: {missing_fields}")
                    self.test_results["failed"] += 1
                    self.test_results["errors"].append(
                        f"{stock['name']}: 缺少字段 {missing_fields}"
                    )
                    continue

                # 打印关键数据
                print(f"✅ 获取成功 ({duration:.2f}s)")
                print(f"   名称: {data.get('name')}")
                print(f"   当前价: {data.get('nowPri')}")
                print(f"   涨跌额: {data.get('increase')}")
                print(f"   涨跌幅: {data.get('increPer')}%")
                print(f"   成交量: {data.get('traAmount', 'N/A')}")
                print(f"   成交额: {data.get('traNumber', 'N/A')}")

                self.test_results["passed"] += 1

            return True

        except Exception as e:
            error_msg = f"场景1异常: {type(e).__name__}: {str(e)}"
            print(f"❌ {error_msg}")
            logger.error(traceback.format_exc())
            self.test_results["failed"] += 1
            self.test_results["errors"].append(error_msg)
            return False
        finally:
            if mcp_client and mcp_client.is_connected:
                await mcp_client.disconnect()

    async def scenario_2_stock_search(self) -> bool:
        """
        场景2: 股票搜索功能

        测试内容:
        - 搜索 "茅台"
        - 搜索 "600519"
        - 验证搜索结果格式
        """
        print("\n" + "="*80)
        print("场景2: 股票搜索功能")
        print("="*80)

        mcp_client = None
        try:
            # 启动 MCP Server
            mcp_client = MCPClient(
                server_script_path=self.server_script_path,
                connect_timeout=15.0,
                call_timeout=15.0
            )

            connected = await mcp_client.connect()
            if not connected:
                print("❌ MCP Server 启动失败")
                self.test_results["failed"] += 1
                return False

            print(f"✅ MCP Server 启动成功")

            # 测试搜索列表
            test_searches = [
                {"keyword": "茅台", "desc": "按名称搜索"},
                {"keyword": "600519", "desc": "按代码搜索"},
            ]

            for search in test_searches:
                print(f"\n🔍 {search['desc']}: '{search['keyword']}'")

                start_time = time.time()
                result = await mcp_client.call_tool(
                    "market_data.search_stock",
                    {"keyword": search["keyword"]}
                )
                duration = time.time() - start_time

                success = result.get("success", False)
                self.performance.record(
                    f"search_stock({search['keyword']})",
                    duration,
                    success,
                    search['desc']
                )

                if not success:
                    error = result.get("error", "未知错误")
                    print(f"❌ 搜索失败: {error}")
                    self.test_results["failed"] += 1
                    self.test_results["errors"].append(f"搜索 {search['keyword']}: {error}")
                    continue

                # 验证结果
                data = result.get("data", {})
                results = data.get("results", []) if isinstance(data, dict) else []
                count = len(results)

                print(f"✅ 搜索成功 ({duration:.2f}s)")
                print(f"   找到 {count} 个结果")

                if results:
                    for i, stock in enumerate(results[:3], 1):  # 只显示前3个
                        print(f"   {i}. {stock.get('name', 'N/A')} ({stock.get('gid', 'N/A')})")

                self.test_results["passed"] += 1

            return True

        except Exception as e:
            error_msg = f"场景2异常: {type(e).__name__}: {str(e)}"
            print(f"❌ {error_msg}")
            logger.error(traceback.format_exc())
            self.test_results["failed"] += 1
            self.test_results["errors"].append(error_msg)
            return False
        finally:
            if mcp_client and mcp_client.is_connected:
                await mcp_client.disconnect()

    async def scenario_3_mcp_client_integration(self) -> bool:
        """
        场景3: MCP Client 真实调用

        测试内容:
        - 启动 MCP Server
        - 验证连接状态
        - 执行多次调用
        - 验证数据一致性
        """
        print("\n" + "="*80)
        print("场景3: MCP Client 真实调用")
        print("="*80)

        mcp_client = None
        try:
            # 启动 MCP Server
            start_time = time.time()
            mcp_client = MCPClient(
                server_script_path=self.server_script_path,
                connect_timeout=15.0,
                call_timeout=15.0
            )

            connected = await mcp_client.connect()
            connect_duration = time.time() - start_time

            if not connected:
                print("❌ MCP Client 连接失败")
                self.test_results["failed"] += 1
                return False

            print(f"✅ MCP Client 连接成功 ({connect_duration:.2f}s)")
            print(f"   连接状态: {mcp_client.is_connected}")
            self.test_results["passed"] += 1

            # 获取工具列表
            print("\n🔧 获取可用工具...")
            start_time = time.time()
            tools_result = await mcp_client.list_tools()
            tools_duration = time.time() - start_time

            if tools_result.get("success"):
                tools = tools_result.get("tools", [])
                print(f"✅ 获取工具列表成功 ({tools_duration:.2f}s)")
                print(f"   可用工具数: {len(tools)}")
                for tool in tools:
                    print(f"   - {tool['name']}: {tool.get('description', '')[:50]}...")
                self.test_results["passed"] += 1
            else:
                print(f"❌ 获取工具列表失败")
                self.test_results["failed"] += 1

            # 执行多次调用测试数据一致性
            print("\n🔄 测试数据一致性...")
            test_code = "600519"
            results = []

            for i in range(3):
                start_time = time.time()
                result = await mcp_client.call_tool(
                    "market_data.get_quote",
                    {"symbol": test_code}
                )
                duration = time.time() - start_time

                if result.get("success"):
                    data = result.get("data", {})
                    results.append(data)
                    print(f"   第{i+1}次调用成功 ({duration:.2f}s) - 价格: {data.get('nowPri')}")
                else:
                    print(f"   第{i+1}次调用失败")

                # 短暂延迟
                await asyncio.sleep(0.5)

            # 验证一致性
            if len(results) == 3:
                names = [r.get("name") for r in results]
                if len(set(names)) == 1:
                    print(f"✅ 数据一致性验证通过 - 股票名称一致: {names[0]}")
                    self.test_results["passed"] += 1
                else:
                    print(f"❌ 数据一致性验证失败 - 名称不一致: {names}")
                    self.test_results["failed"] += 1

            return True

        except Exception as e:
            error_msg = f"场景3异常: {type(e).__name__}: {str(e)}"
            print(f"❌ {error_msg}")
            logger.error(traceback.format_exc())
            self.test_results["failed"] += 1
            self.test_results["errors"].append(error_msg)
            return False
        finally:
            if mcp_client and mcp_client.is_connected:
                await mcp_client.disconnect()

    async def scenario_4_tool_adapter(self) -> bool:
        """
        场景4: 完整链路测试 (ToolAdapter)

        测试内容:
        - 通过 ToolAdapter 获取股票数据
        - 验证数据格式符合 DeepResearch 要求
        - 测试降级机制
        """
        print("\n" + "="*80)
        print("场景4: 完整链路测试 (ToolAdapter)")
        print("="*80)

        mcp_client = None
        try:
            # 启动 MCP Server
            mcp_client = MCPClient(
                server_script_path=self.server_script_path,
                connect_timeout=15.0,
                call_timeout=15.0
            )

            connected = await mcp_client.connect()
            if not connected:
                print("❌ MCP Server 启动失败")
                self.test_results["failed"] += 1
                return False

            print(f"✅ MCP Server 启动成功")

            # 创建 ToolAdapter
            tool_adapter = ToolAdapter(
                mcp_client=mcp_client,
                fallback_enabled=True
            )

            print(f"✅ ToolAdapter 创建成功")
            print(f"   使用 MCP: {tool_adapter.is_using_mcp}")
            print(f"   已降级: {tool_adapter.is_degraded}")
            self.test_results["passed"] += 1

            # 通过 ToolAdapter 获取数据
            test_stocks = ["600519", "000001", "000858"]

            for code in test_stocks:
                print(f"\n📊 获取股票数据: {code}")

                start_time = time.time()
                result = await tool_adapter.get_stock_by_code(code)
                duration = time.time() - start_time

                success = result.get("success", False)
                self.performance.record(
                    f"ToolAdapter.get_stock_by_code({code})",
                    duration,
                    success,
                    "通过 ToolAdapter"
                )

                if not success:
                    error = result.get("error", "未知错误")
                    print(f"❌ 获取失败: {error}")
                    self.test_results["failed"] += 1
                    continue

                # 验证数据格式（DeepResearch 需要的格式）
                data = result.get("data", {})
                required_fields = ["name", "nowPri", "increase", "increPer"]
                missing = [f for f in required_fields if f not in data]

                if missing:
                    print(f"❌ 数据格式不符合要求，缺少: {missing}")
                    self.test_results["failed"] += 1
                    continue

                print(f"✅ 数据获取成功 ({duration:.2f}s)")
                print(f"   名称: {data.get('name')}")
                print(f"   当前价: {data.get('nowPri')}")
                print(f"   涨跌幅: {data.get('increPer')}%")
                print(f"   使用 MCP: {tool_adapter.is_using_mcp}")

                self.test_results["passed"] += 1

            return True

        except Exception as e:
            error_msg = f"场景4异常: {type(e).__name__}: {str(e)}"
            print(f"❌ {error_msg}")
            logger.error(traceback.format_exc())
            self.test_results["failed"] += 1
            self.test_results["errors"].append(error_msg)
            return False
        finally:
            if mcp_client and mcp_client.is_connected:
                await mcp_client.disconnect()

    def generate_report(self) -> str:
        """生成测试报告"""
        report_lines = []
        report_lines.append("# 真实环境端到端集成测试报告")
        report_lines.append("")
        report_lines.append(f"**测试时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append(f"**API Token**: 已配置 (Tushare)")
        report_lines.append("")

        # 测试结果
        report_lines.append("## 测试结果")
        report_lines.append("")
        total = self.test_results["passed"] + self.test_results["failed"]
        pass_rate = (self.test_results["passed"] / total * 100) if total > 0 else 0

        report_lines.append(f"- **总测试数**: {total}")
        report_lines.append(f"- **通过**: {self.test_results['passed']} ✅")
        report_lines.append(f"- **失败**: {self.test_results['failed']} ❌")
        report_lines.append(f"- **通过率**: {pass_rate:.1f}%")
        report_lines.append("")

        # 性能数据
        perf_summary = self.performance.get_summary()
        if perf_summary:
            report_lines.append("## 性能数据")
            report_lines.append("")
            report_lines.append(f"- **总操作数**: {perf_summary['total_operations']}")
            report_lines.append(f"- **成功操作**: {perf_summary['successful']}")
            report_lines.append(f"- **失败操作**: {perf_summary['failed']}")
            report_lines.append(f"- **平均响应时间**: {perf_summary['avg_duration_ms']}ms")
            report_lines.append(f"- **最快响应**: {perf_summary['min_duration_ms']}ms")
            report_lines.append(f"- **最慢响应**: {perf_summary['max_duration_ms']}ms")
            report_lines.append(f"- **总耗时**: {perf_summary['total_duration_s']}s")
            report_lines.append("")

            # 详细性能数据
            report_lines.append("### 详细性能数据")
            report_lines.append("")
            report_lines.append("| 操作 | 耗时(ms) | 状态 | 备注 |")
            report_lines.append("|------|---------|------|------|")

            for m in self.performance.metrics:
                status = "✅" if m["success"] else "❌"
                report_lines.append(
                    f"| {m['operation']} | {m['duration_ms']} | {status} | {m['details']} |"
                )
            report_lines.append("")

        # 错误详情
        if self.test_results["errors"]:
            report_lines.append("## 发现的问题")
            report_lines.append("")
            for i, error in enumerate(self.test_results["errors"], 1):
                report_lines.append(f"{i}. {error}")
            report_lines.append("")
        else:
            report_lines.append("## 发现的问题")
            report_lines.append("")
            report_lines.append("✅ 未发现问题，所有测试通过")
            report_lines.append("")

        # 结论
        report_lines.append("## 测试结论")
        report_lines.append("")
        if self.test_results["failed"] == 0:
            report_lines.append("✅ **所有测试通过**，MCP 架构在真实环境下运行正常。")
        else:
            report_lines.append(f"⚠️ **发现 {self.test_results['failed']} 个失败**，需要进一步排查。")
        report_lines.append("")

        report_lines.append("---")
        report_lines.append(f"*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")

        return "\n".join(report_lines)

    async def run_all_tests(self):
        """运行所有测试"""
        print("\n" + "="*80)
        print("真实环境端到端集成测试")
        print("="*80)
        print(f"测试开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)

        # 检查环境
        if not self.check_environment():
            print("\n❌ 环境检查失败，测试终止")
            return False

        # 运行测试场景
        scenarios = [
            ("场景1: 真实股票数据获取", self.scenario_1_real_stock_data),
            ("场景2: 股票搜索功能", self.scenario_2_stock_search),
            ("场景3: MCP Client 真实调用", self.scenario_3_mcp_client_integration),
            ("场景4: 完整链路测试 (ToolAdapter)", self.scenario_4_tool_adapter),
        ]

        all_passed = True
        for name, scenario_func in scenarios:
            passed = await scenario_func()
            if not passed:
                all_passed = False

        # 打印性能数据
        self.performance.print_details()

        # 打印摘要
        print("\n" + "="*80)
        print("测试摘要")
        print("="*80)
        print(f"总通过: {self.test_results['passed']} ✅")
        print(f"总失败: {self.test_results['failed']} ❌")

        perf_summary = self.performance.get_summary()
        if perf_summary:
            print(f"\n性能摘要:")
            print(f"  平均响应时间: {perf_summary['avg_duration_ms']}ms")
            print(f"  总耗时: {perf_summary['total_duration_s']}s")

        if all_passed and self.test_results['failed'] == 0:
            print("\n🎉 所有测试通过!")
        else:
            print(f"\n⚠️ 发现 {self.test_results['failed']} 个失败")

        print("="*80)

        # 生成报告
        report = self.generate_report()
        report_path = os.path.join(
            os.path.dirname(__file__),
            "REAL_E2E_TEST_REPORT.md"
        )
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)

        print(f"\n📄 测试报告已保存到: {report_path}")

        return all_passed


async def main():
    """主函数"""
    test = RealE2ETest()
    await test.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())
