#!/usr/bin/env python3
"""测试 DeepResearch Skill 的工具"""

import asyncio
import sys
import os
import json

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.mcp_server.skills.deep_research import DeepResearchSkill


async def test_quick_research():
    """测试快速研究功能"""
    print("\n" + "=" * 60)
    print("测试 1: quick_research")
    print("=" * 60)

    skill = DeepResearchSkill()

    result = await skill.quick_research(
        query="茅台股票近期表现",
        max_iterations=2  # 限制为2次迭代以加快速度
    )

    print(f"\n✅ 测试完成")
    print(f"成功: {result.get('success')}")
    if result.get('success'):
        print(f"查询: {result.get('query')}")
        print(f"摘要: {result.get('summary', '')[:200]}...")
        print(f"质量评分: {result.get('quality_score')}")
        print(f"迭代次数: {result.get('iterations')}")
    else:
        print(f"错误: {result.get('error')}")


async def test_research_sync():
    """测试同步研究功能"""
    print("\n" + "=" * 60)
    print("测试 2: research_sync")
    print("=" * 60)

    skill = DeepResearchSkill()

    result = await skill.research_sync(
        query="平安银行2024年财务状况简要分析",
        search_web=True
    )

    print(f"\n✅ 测试完成")
    print(f"成功: {result.get('success')}")
    if result.get('success'):
        print(f"查询: {result.get('query')}")
        print(f"会话ID: {result.get('session_id')}")
        print(f"质量评分: {result.get('quality_score')}")
        print(f"迭代次数: {result.get('iterations')}")
        print(f"报告长度: {len(result.get('final_report', ''))} 字符")
        print(f"事实数量: {len(result.get('facts', []))}")
        print(f"洞察数量: {len(result.get('insights', []))}")
    else:
        print(f"错误: {result.get('error')}")


async def test_tool_discovery():
    """测试工具发现"""
    print("\n" + "=" * 60)
    print("测试 3: 工具发现")
    print("=" * 60)

    skill = DeepResearchSkill()

    print(f"\nSkill 名称: {skill.name}")
    print(f"工具数量: {skill.tool_count}")
    print(f"\n工具列表:")

    for tool_def in skill.discover_tools():
        print(f"\n  📌 {tool_def.name}")
        print(f"     描述: {tool_def.description[:80]}...")
        print(f"     参数:")
        for param in tool_def.parameters:
            required_mark = "必填" if param.required else "可选"
            print(f"       - {param.name} ({param.type}, {required_mark}): {param.description[:60]}...")


async def main():
    """主测试函数"""
    print("\n🧪 DeepResearch Skill 测试")
    print("=" * 60)

    # 测试1: 工具发现
    await test_tool_discovery()

    # 测试2: 快速研究（如果配置了API密钥）
    if os.environ.get("DASHSCOPE_API_KEY"):
        try:
            await test_quick_research()
        except Exception as e:
            print(f"\n⚠️ 快速研究测试失败: {e}")
    else:
        print("\n⚠️ 跳过快速研究测试（未配置 DASHSCOPE_API_KEY）")

    # 测试3: 同步研究（如果配置了API密钥）
    if os.environ.get("DASHSCOPE_API_KEY"):
        try:
            await test_research_sync()
        except Exception as e:
            print(f"\n⚠️ 同步研究测试失败: {e}")
    else:
        print("\n⚠️ 跳过同步研究测试（未配置 DASHSCOPE_API_KEY）")

    print("\n" + "=" * 60)
    print("✅ 所有测试完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
