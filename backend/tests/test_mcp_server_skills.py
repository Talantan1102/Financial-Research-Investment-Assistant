#!/usr/bin/env python3
"""
MCP Server Skill 注册测试脚本
验证三个核心 Skill 是否正确注册
"""

import sys
import os

# 添加项目路径
backend_dir = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, backend_dir)

from app.mcp_server.skills import MarketDataSkill, FinancialAnalysisSkill, RiskAssessmentSkill
from app.data.tushare_client import get_tushare_client

# 设置环境变量
os.environ['TUSHARE_API_TOKEN'] = '9e4123cf56aaa553b06556e64b05e9d8d004340d82897eb1704ccd91c088'
os.environ['TUSHARE_API_URL'] = 'http://lianghua.nanyangqiankun.top'

def test_skill_registration():
    """测试 Skill 注册"""
    print("=" * 60)
    print("🧪 MCP Server Skill 注册测试")
    print("=" * 60)
    
    skills = {}
    total_tools = 0
    
    # 1. 测试 MarketDataSkill
    print("\n📊 1. MarketDataSkill")
    try:
        skill = MarketDataSkill()
        skills[skill.name] = skill
        tools = skill.discover_tools()
        print(f"   ✅ 注册成功: {skill.name}")
        print(f"   🛠️  工具数量: {skill.tool_count}")
        for tool in tools:
            print(f"      - {tool.name}: {tool.description[:50]}...")
        total_tools += skill.tool_count
    except Exception as e:
        print(f"   ❌ 注册失败: {e}")
        return False
    
    # 2. 测试 FinancialAnalysisSkill
    print("\n📈 2. FinancialAnalysisSkill")
    try:
        skill = FinancialAnalysisSkill()
        skills[skill.name] = skill
        tools = skill.discover_tools()
        print(f"   ✅ 注册成功: {skill.name}")
        print(f"   🛠️  工具数量: {skill.tool_count}")
        for tool in tools:
            print(f"      - {tool.name}: {tool.description[:50]}...")
        total_tools += skill.tool_count
    except Exception as e:
        print(f"   ❌ 注册失败: {e}")
        return False
    
    # 3. 测试 RiskAssessmentSkill
    print("\n⚠️  3. RiskAssessmentSkill")
    try:
        skill = RiskAssessmentSkill()
        skills[skill.name] = skill
        tools = skill.discover_tools()
        print(f"   ✅ 注册成功: {skill.name}")
        print(f"   🛠️  工具数量: {skill.tool_count}")
        for tool in tools:
            print(f"      - {tool.name}: {tool.description[:50]}...")
        total_tools += skill.tool_count
    except Exception as e:
        print(f"   ❌ 注册失败: {e}")
        return False
    
    # 汇总
    print("\n" + "=" * 60)
    print("📋 测试结果汇总")
    print("=" * 60)
    print(f"   ✅ 注册成功的 Skill 数量: {len(skills)}")
    print(f"   ✅ 总工具数量: {total_tools}")
    
    # 验证工具总数是否为 9
    if total_tools == 9:
        print(f"   ✅ 工具总数验证通过 (期望: 9, 实际: {total_tools})")
    else:
        print(f"   ⚠️  工具总数不匹配 (期望: 9, 实际: {total_tools})")
    
    # 列出所有工具
    print("\n📜 完整工具列表:")
    for skill_name, skill in skills.items():
        for tool_def in skill.discover_tools():
            full_name = f"{skill_name}.{tool_def.name}"
            print(f"   - {full_name}")
    
    print("\n" + "=" * 60)
    print("🎉 MCP Server Skill 注册测试完成!")
    print("=" * 60)
    
    return True

if __name__ == "__main__":
    success = test_skill_registration()
    sys.exit(0 if success else 1)
