#!/usr/bin/env python3
"""
金融研投助手 - 控制流测试（简化版）

测试复杂任务编排能力：
1. 多工具协同（Sequential）
2. 批量处理（For-Each）
3. LLM 驱动的完整流程
"""

import json
import asyncio
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend', 'app'))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', 'backend', '.env'))
except ImportError:
    pass

from app.mcp_client.client import mcp_client_context


@dataclass
class TestResult:
    test_id: str
    test_name: str
    flow_type: str
    success: bool
    latency_ms: int
    error: Optional[str]
    details: Dict


def extract_result(result) -> Dict:
    """提取 MCP 结果"""
    if isinstance(result, dict):
        return result
    if hasattr(result, 'content') and result.content:
        try:
            return json.loads(result.content[0].text)
        except:
            return {"success": True, "data": result.content[0].text[:500]}
    return {"success": False, "error": f"Unknown type: {type(result)}"}


async def test_simple_tool_call():
    """测试 1: 单一工具调用"""
    print("\n📋 测试 1: 单一工具调用 (get_quote)")
    
    async with mcp_client_context(
        os.path.join(os.path.dirname(__file__), '..', 'backend', 'app', 'mcp_server', 'server.py'),
        os.environ.get('PYTHON', sys.executable)
    ) as session:
        start = time.time()
        
        result = await session.call_tool("execute_skill_tool", {
            "skill_name": "market_data",
            "tool_name": "get_quote",
            "arguments": {"ts_code": "600519.SH"}
        })
        
        data = extract_result(result)
        latency = int((time.time() - start) * 1000)
        
        success = data.get("success", False)
        print(f"  {'✅' if success else '❌'} {'成功' if success else '失败'} | {latency}ms")
        
        return TestResult("T1", "单一工具调用", "single", success, latency, 
                         None if success else data.get("error"), data)


async def test_sequential():
    """测试 2: 顺序执行多个工具"""
    print("\n📋 测试 2: 顺序执行 (行情 → 估值 → 财务)")
    
    async with mcp_client_context(
        os.path.join(os.path.dirname(__file__), '..', 'backend', 'app', 'mcp_server', 'server.py'),
        os.environ.get('PYTHON', sys.executable)
    ) as session:
        start = time.time()
        steps = []
        
        # Step 1: 行情
        r1 = extract_result(await session.call_tool("execute_skill_tool", {
            "skill_name": "market_data", "tool_name": "get_quote", "arguments": {"ts_code": "600519.SH"}
        }))
        steps.append(("get_quote", r1.get("success", False)))
        
        # Step 2: 估值
        r2 = extract_result(await session.call_tool("execute_skill_tool", {
            "skill_name": "market_data", "tool_name": "get_daily_basic", "arguments": {"ts_code": "600519.SH"}
        }))
        steps.append(("get_daily_basic", r2.get("success", False)))
        
        # Step 3: 财务
        r3 = extract_result(await session.call_tool("execute_skill_tool", {
            "skill_name": "financial_analysis", "tool_name": "calculate_financial_ratios", "arguments": {"ts_code": "600519.SH"}
        }))
        steps.append(("calculate_financial_ratios", r3.get("success", False)))
        
        latency = int((time.time() - start) * 1000)
        all_success = all(s[1] for s in steps)
        
        print(f"  {'✅' if all_success else '❌'} 顺序执行 | 步骤: {len([s for s in steps if s[1]])}/3 | {latency}ms")
        for name, ok in steps:
            print(f"      {'✓' if ok else '✗'} {name}")
        
        return TestResult("T2", "顺序执行", "sequential", all_success, latency,
                         None, {"steps": steps})


async def test_parallel():
    """测试 3: 并行执行（For-Each）"""
    print("\n📋 测试 3: 并行执行 (批量查询3只股票)")
    
    async with mcp_client_context(
        os.path.join(os.path.dirname(__file__), '..', 'backend', 'app', 'mcp_server', 'server.py'),
        os.environ.get('PYTHON', sys.executable)
    ) as session:
        start = time.time()
        
        stocks = ["600519.SH", "000858.SZ", "600809.SH"]
        tasks = []
        
        for ts_code in stocks:
            task = session.call_tool("execute_skill_tool", {
                "skill_name": "market_data",
                "tool_name": "get_quote",
                "arguments": {"ts_code": ts_code}
            })
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        success_count = 0
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                print(f"      ✗ {stocks[i]}: {r}")
            else:
                data = extract_result(r)
                if data.get("success"):
                    success_count += 1
                    print(f"      ✓ {stocks[i]}")
                else:
                    print(f"      ✗ {stocks[i]}: {data.get('error', 'Unknown')}")
        
        latency = int((time.time() - start) * 1000)
        all_success = success_count == len(stocks)
        
        print(f"  {'✅' if all_success else '⚠️'} 并行执行 | 成功: {success_count}/{len(stocks)} | {latency}ms")
        
        return TestResult("T3", "并行执行", "parallel", all_success, latency,
                         None, {"stocks": stocks, "success_count": success_count})


async def test_control_flow_engine():
    """测试 4: 控制流引擎"""
    print("\n📋 测试 4: Control Flow Engine (sequential)")
    
    async with mcp_client_context(
        os.path.join(os.path.dirname(__file__), '..', 'backend', 'app', 'mcp_server', 'server.py'),
        os.environ.get('PYTHON', sys.executable)
    ) as session:
        start = time.time()
        
        # 测试 control flow 引擎
        result = await session.call_tool("execute_control_flow", {
            "flow_type": "sequential",
            "config": {
                "calls": [
                    {"skill": "market_data", "tool": "get_quote", "arguments": {"ts_code": "600519.SH"}},
                    {"skill": "market_data", "tool": "get_daily_basic", "arguments": {"ts_code": "600519.SH"}}
                ]
            }
        })
        
        data = extract_result(result)
        latency = int((time.time() - start) * 1000)
        success = data.get("success", False)
        
        print(f"  {'✅' if success else '❌'} Control Flow | {latency}ms")
        if success:
            summary = data.get("summary", {})
            print(f"      步骤: {summary.get('total', 0)}, 成功: {summary.get('successful', 0)}")
        else:
            print(f"      错误: {data.get('error', 'Unknown')}")
        
        return TestResult("T4", "Control Flow Engine", "control_flow", success, latency,
                         data.get("error"), data)


async def test_cross_skill():
    """测试 5: 跨 Skill 复杂流程"""
    print("\n📋 测试 5: 跨 Skill 复杂流程 (综合分析)")
    
    async with mcp_client_context(
        os.path.join(os.path.dirname(__file__), '..', 'backend', 'app', 'mcp_server', 'server.py'),
        os.environ.get('PYTHON', sys.executable)
    ) as session:
        start = time.time()
        
        # 模拟一个综合分析流程
        steps = []
        
        # 1. 获取行情
        r1 = extract_result(await session.call_tool("execute_skill_tool", {
            "skill_name": "market_data", "tool_name": "get_quote", "arguments": {"ts_code": "600519.SH"}
        }))
        steps.append(("market_data.get_quote", r1.get("success", False)))
        
        # 2. 获取估值
        r2 = extract_result(await session.call_tool("execute_skill_tool", {
            "skill_name": "market_data", "tool_name": "get_daily_basic", "arguments": {"ts_code": "600519.SH"}
        }))
        steps.append(("market_data.get_daily_basic", r2.get("success", False)))
        
        # 3. 获取财务指标
        r3 = extract_result(await session.call_tool("execute_skill_tool", {
            "skill_name": "financial_analysis", "tool_name": "get_fina_indicator", "arguments": {"ts_code": "600519.SH"}
        }))
        steps.append(("financial_analysis.get_fina_indicator", r3.get("success", False)))
        
        # 4. 风险评估
        r4 = extract_result(await session.call_tool("execute_skill_tool", {
            "skill_name": "risk_assessment", "tool_name": "assess_stock_risk", "arguments": {"ts_code": "600519.SH"}
        }))
        steps.append(("risk_assessment.assess_stock_risk", r4.get("success", False)))
        
        latency = int((time.time() - start) * 1000)
        success_count = sum(1 for _, ok in steps if ok)
        all_success = success_count == len(steps)
        
        print(f"  {'✅' if all_success else '⚠️'} 综合分析 | 成功: {success_count}/{len(steps)} | {latency}ms")
        for name, ok in steps:
            print(f"      {'✓' if ok else '✗'} {name}")
        
        return TestResult("T5", "跨 Skill 综合分析", "cross_skill", all_success, latency,
                         None, {"steps": steps})


async def main():
    print("="*70)
    print("🧪 金融研投助手 - 控制流测试")
    print("="*70)
    
    results = []
    
    # 运行所有测试
    results.append(await test_simple_tool_call())
    results.append(await test_sequential())
    results.append(await test_parallel())
    results.append(await test_control_flow_engine())
    results.append(await test_cross_skill())
    
    # 汇总
    print("\n" + "="*70)
    print("📊 测试汇总")
    print("="*70)
    
    passed = sum(1 for r in results if r.success)
    total = len(results)
    
    for r in results:
        status = "✅ PASS" if r.success else "❌ FAIL"
        print(f"{status} | {r.test_id}: {r.test_name} ({r.latency_ms}ms)")
    
    print(f"\n总计: {passed}/{total} 通过 ({passed/total*100:.0f}%)")
    print("="*70)
    
    # 保存报告
    report = {
        "timestamp": datetime.now().isoformat(),
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "results": [asdict(r) for r in results]
    }
    
    report_file = f"control_flow_simple_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 报告已保存: {report_file}")


if __name__ == '__main__':
    asyncio.run(main())
