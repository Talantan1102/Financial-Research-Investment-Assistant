#!/usr/bin/env python3
"""
Tool 可用性验证脚本
直接调用 Skill 的 tools 来验证它们是否能成功执行
"""

import json
import asyncio
import sys
import os
from datetime import datetime
from typing import Dict, Any, List, Tuple

# 添加项目路径
backend_path = os.path.join(os.path.dirname(__file__), '..', 'backend')
sys.path.insert(0, backend_path)

print(f"Python path: {sys.path[0]}")
print(f"Backend path: {backend_path}")

# 检查路径是否存在
if os.path.exists(backend_path):
    print(f"✅ Backend 路径存在")
    skills_path = os.path.join(backend_path, 'app', 'mcp_server', 'skills')
    print(f"Skills 路径: {skills_path}")
    if os.path.exists(skills_path):
        print(f"✅ Skills 路径存在")
        files = os.listdir(skills_path)
        print(f"   文件: {files}")
else:
    print(f"❌ Backend 路径不存在: {backend_path}")
    sys.exit(1)

# 检查环境变量
token = os.getenv("TUSHARE_API_TOKEN", "")
url = os.getenv("TUSHARE_API_URL", "")
print(f"\n🔑 TUSHARE_API_TOKEN: {'已设置' if token else '未设置'} ({token[:20] + '...' if token else ''})")
print(f"🌐 TUSHARE_API_URL: {url if url else '未设置 (使用默认 https://api.tushare.pro)'}")

try:
    from app.mcp_server.skills.market_data import MarketDataSkill
    from app.mcp_server.skills.financial_analysis import FinancialAnalysisSkill
    from app.mcp_server.skills.sector_analysis import SectorAnalysisSkill
    from app.mcp_server.skills.risk_assessment import RiskAssessmentSkill
    from app.mcp_server.skills.web_research import WebResearchSkill
    from app.mcp_server.skills.data_analysis import DataAnalysisSkill
    from app.mcp_server.skills.deep_research import DeepResearchSkill
    print("✅ 所有 Skill 导入成功")
except Exception as e:
    print(f"❌ 导入失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)


class ToolValidator:
    """工具可用性验证器"""
    
    def __init__(self):
        print("\n初始化 Skills...")
        self.skills = {}
        
        skill_classes = {
            "market_data": MarketDataSkill,
            "financial_analysis": FinancialAnalysisSkill,
            "sector_analysis": SectorAnalysisSkill,
            "risk_assessment": RiskAssessmentSkill,
            "web_research": WebResearchSkill,
            "data_analysis": DataAnalysisSkill,
            "deep_research": DeepResearchSkill,
        }
        
        for name, cls in skill_classes.items():
            try:
                self.skills[name] = cls()
                print(f"  ✅ {name}")
            except Exception as e:
                print(f"  ❌ {name}: {e}")
        
        self.results = []
        
    def load_test_cases(self, filepath: str) -> List[Dict]:
        """加载测试用例 - 处理带注释的 JSON"""
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # 过滤掉注释行和空行
        json_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith('#') and not stripped.startswith('---'):
                json_lines.append(line)
        
        # 合并并解析 JSON
        json_content = ''.join(json_lines)
        try:
            return json.loads(json_content)
        except json.JSONDecodeError as e:
            print(f"❌ JSON 解析失败: {e}")
            # 尝试逐行解析
            test_cases = []
            for line in json_lines:
                try:
                    if line.strip().startswith('{') or line.strip().startswith('['):
                        data = json.loads(line.strip())
                        if isinstance(data, list):
                            test_cases.extend(data)
                        else:
                            test_cases.append(data)
                except:
                    continue
            return test_cases
    
    async def validate_test_case(self, test_case: Dict) -> Dict[str, Any]:
        """验证单个测试用例"""
        test_id = test_case.get('id', 'unknown')
        query = test_case.get('query', '')
        expected_skill = test_case.get('expected_skill')
        expected_tool = test_case.get('expected_tool')
        expected_params = test_case.get('expected_params', {})
        
        print(f"\n{'='*60}")
        print(f"测试: {test_id}")
        print(f"查询: {query}")
        print(f"预期 Skill: {expected_skill}")
        print(f"预期 Tool: {expected_tool}")
        print(f"预期参数: {expected_params}")
        print(f"{'='*60}")
        
        result = {
            "test_id": test_id,
            "query": query,
            "expected_skill": expected_skill,
            "expected_tool": expected_tool,
            "expected_params": expected_params,
            "actual_skill": None,
            "actual_tool": None,
            "tool_exists": False,
            "execution_success": False,
            "error": None,
            "response_preview": None,
            "timestamp": datetime.now().isoformat()
        }
        
        # 如果没有预期 skill，跳过工具调用
        if not expected_skill:
            print("⏭️  NO-SKILL 用例，跳过工具调用")
            result["status"] = "SKIPPED"
            return result
        
        # 获取 Skill 实例
        skill = self.skills.get(expected_skill)
        if not skill:
            result["error"] = f"Skill '{expected_skill}' 不存在"
            result["status"] = "SKILL_NOT_FOUND"
            print(f"❌ Skill 不存在: {expected_skill}")
            return result
        
        result["actual_skill"] = expected_skill
        
        # 检查 Tool 是否存在
        if not skill.has_tool(expected_tool):
            result["error"] = f"Tool '{expected_tool}' 不存在于 Skill '{expected_skill}'"
            result["status"] = "TOOL_NOT_FOUND"
            print(f"❌ Tool 不存在: {expected_skill}.{expected_tool}")
            # 打印可用的 tools
            available_tools = list(skill._tools.keys())
            print(f"   可用 Tools: {available_tools}")
            return result
        
        result["tool_exists"] = True
        result["actual_tool"] = expected_tool
        print(f"✅ Tool 存在: {expected_skill}.{expected_tool}")
        
        # 执行工具
        try:
            from app.mcp_server.skills.base import ToolResult
            tool_result = await skill.execute_tool(expected_tool, expected_params)
            
            if tool_result.success:
                result["execution_success"] = True
                result["status"] = "SUCCESS"
                # 只取部分数据作为预览
                data_preview = str(tool_result.data)[:200] if tool_result.data else "None"
                result["response_preview"] = data_preview
                print(f"✅ 执行成功")
                print(f"   响应预览: {data_preview}...")
            else:
                result["execution_success"] = False
                result["error"] = tool_result.error
                result["status"] = "EXECUTION_FAILED"
                print(f"❌ 执行失败: {tool_result.error}")
                
        except Exception as e:
            result["execution_success"] = False
            result["error"] = str(e)
            result["status"] = "EXCEPTION"
            print(f"❌ 执行异常: {e}")
            import traceback
            traceback.print_exc()
        
        return result
    
    async def run_all_tests(self, test_cases: List[Dict]) -> Dict[str, Any]:
        """运行所有测试"""
        print("\n" + "="*60)
        print("开始验证 Tool 可用性")
        print(f"总测试数: {len(test_cases)}")
        print("="*60)
        
        for i, test_case in enumerate(test_cases, 1):
            print(f"\n进度: {i}/{len(test_cases)}")
            result = await self.validate_test_case(test_case)
            self.results.append(result)
        
        return self._generate_report()
    
    def _generate_report(self) -> Dict[str, Any]:
        """生成测试报告"""
        total = len(self.results)
        if total == 0:
            return {"error": "No test results"}
        
        # 统计
        success = sum(1 for r in self.results if r["status"] == "SUCCESS")
        failed = sum(1 for r in self.results if r["status"] in ["EXECUTION_FAILED", "EXCEPTION"])
        tool_not_found = sum(1 for r in self.results if r["status"] == "TOOL_NOT_FOUND")
        skill_not_found = sum(1 for r in self.results if r["status"] == "SKILL_NOT_FOUND")
        skipped = sum(1 for r in self.results if r["status"] == "SKIPPED")
        
        # 按 Skill 分组统计
        skill_stats = {}
        for r in self.results:
            skill = r["expected_skill"] or "NO_SKILL"
            if skill not in skill_stats:
                skill_stats[skill] = {"total": 0, "success": 0, "failed": 0}
            skill_stats[skill]["total"] += 1
            if r["status"] == "SUCCESS":
                skill_stats[skill]["success"] += 1
            elif r["status"] in ["EXECUTION_FAILED", "EXCEPTION", "TOOL_NOT_FOUND"]:
                skill_stats[skill]["failed"] += 1
        
        report = {
            "timestamp": datetime.now().isoformat(),
            "total_tests": total,
            "summary": {
                "success": success,
                "failed": failed,
                "tool_not_found": tool_not_found,
                "skill_not_found": skill_not_found,
                "skipped": skipped,
                "success_rate": success / (total - skipped) if (total - skipped) > 0 else 0
            },
            "skill_breakdown": skill_stats,
            "failed_tests": [r for r in self.results if r["status"] in ["EXECUTION_FAILED", "EXCEPTION", "TOOL_NOT_FOUND"]],
            "all_results": self.results
        }
        
        return report
    
    def print_report(self, report: Dict[str, Any]):
        """打印测试报告"""
        summary = report["summary"]
        
        print("\n" + "="*60)
        print("Tool 可用性验证报告")
        print("="*60)
        print(f"总测试数: {report['total_tests']}")
        print(f"\n📊 汇总:")
        print(f"  ✅ 执行成功: {summary['success']}")
        print(f"  ❌ 执行失败: {summary['failed']}")
        print(f"  ⚠️  Tool 不存在: {summary['tool_not_found']}")
        print(f"  ⚠️  Skill 不存在: {summary['skill_not_found']}")
        print(f"  ⏭️  跳过 (NO-SKILL): {summary['skipped']}")
        print(f"\n📈 成功率: {summary['success_rate']*100:.1f}%")
        
        print(f"\n📋 按 Skill 统计:")
        for skill, stats in report["skill_breakdown"].items():
            rate = stats["success"] / stats["total"] * 100 if stats["total"] > 0 else 0
            print(f"  {skill}: {stats['success']}/{stats['total']} ({rate:.0f}%)")
        
        if report["failed_tests"]:
            print(f"\n❌ 失败的测试:")
            for r in report["failed_tests"]:
                print(f"  - {r['test_id']}: {r['expected_skill']}.{r['expected_tool']}")
                print(f"    错误: {r.get('error', 'Unknown')}")
        
        print("="*60)
    
    def save_report(self, report: Dict[str, Any], filepath: str):
        """保存测试报告"""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n报告已保存: {filepath}")


async def main():
    """主函数"""
    # 测试用例文件路径
    test_cases_file = os.path.join(
        os.path.dirname(__file__), 
        'simple_test_cases.json'
    )
    
    if not os.path.exists(test_cases_file):
        print(f"错误: 测试用例文件不存在: {test_cases_file}")
        return
    
    # 创建验证器
    validator = ToolValidator()
    
    # 加载测试用例
    test_cases = validator.load_test_cases(test_cases_file)
    print(f"\n加载了 {len(test_cases)} 个测试用例")
    
    # 运行测试
    report = await validator.run_all_tests(test_cases)
    
    # 打印报告
    validator.print_report(report)
    
    # 保存报告
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_file = os.path.join(
        os.path.dirname(__file__),
        f'tool_validation_report_{timestamp}.json'
    )
    validator.save_report(report, report_file)


if __name__ == '__main__':
    asyncio.run(main())
