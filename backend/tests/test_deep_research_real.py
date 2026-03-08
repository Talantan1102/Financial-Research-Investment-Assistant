#!/usr/bin/env python3
"""测试 DeepResearch Skill 的实际功能（使用真实 API）"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.mcp_server.skills.deep_research import DeepResearchSkill


async def test_quick_research_real():
    """测试真实的快速研究功能"""
    print("\n" + "=" * 60)
    print("🧪 测试: 快速研究（真实 API 调用）")
    print("=" * 60)

    # 设置 API Key
    os.environ["DASHSCOPE_API_KEY"] = "sk-946dc6cdc78b40829f826a0ca3fb7382"

    skill = DeepResearchSkill()

    print("\n📝 研究问题: 贵州茅台2024年股价表现")
    print("⏳ 执行中（限制2次迭代以加快速度）...\n")

    try:
        result = await skill.quick_research(
            query="贵州茅台2024年股价表现简要分析",
            max_iterations=2  # 限制迭代次数
        )

        print("\n" + "=" * 60)
        print("📊 研究结果")
        print("=" * 60)

        if result.get("success"):
            print(f"\n✅ 研究成功")
            print(f"质量评分: {result.get('quality_score', 0):.2f}")
            print(f"迭代次数: {result.get('iterations', 0)}")

            summary = result.get("summary", "")
            if summary:
                print(f"\n📄 摘要:")
                print(summary)

            key_facts = result.get("key_facts", [])
            if key_facts:
                print(f"\n💡 关键事实 ({len(key_facts)} 条):")
                for i, fact in enumerate(key_facts[:5], 1):
                    content = fact.get("content", "") if isinstance(fact, dict) else str(fact)
                    print(f"  {i}. {content}")

            key_insights = result.get("key_insights", [])
            if key_insights:
                print(f"\n🔍 关键洞察 ({len(key_insights)} 条):")
                for i, insight in enumerate(key_insights[:3], 1):
                    print(f"  {i}. {insight}")

        else:
            print(f"\n❌ 研究失败")
            print(f"错误: {result.get('error', '未知错误')}")

    except Exception as e:
        print(f"\n❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()


async def test_mcp_client_real():
    """测试通过 MCP Client 调用真实研究"""
    print("\n" + "=" * 60)
    print("🧪 测试: 通过 MCP Client 调用（真实 API）")
    print("=" * 60)

    os.environ["DASHSCOPE_API_KEY"] = "sk-946dc6cdc78b40829f826a0ca3fb7382"

    from app.mcp_client.client import MCPClient

    server_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "app/mcp_server/server.py"
    )

    print("\n⏳ 连接 MCP Server...")
    client = MCPClient(server_script_path=server_path)
    await client.connect()
    print("✅ 连接成功")

    print("\n📝 研究问题: 平安银行2024年财务状况")
    print("⏳ 执行中...\n")

    try:
        result = await client.call_tool(
            "deep_research.quick_research",
            {
                "query": "平安银行2024年财务状况简要分析",
                "max_iterations": 2
            }
        )

        print("\n" + "=" * 60)
        print("📊 研究结果")
        print("=" * 60)

        if result.get("success"):
            data = result.get("data", {})
            print(f"\n✅ 研究成功")
            print(f"质量评分: {data.get('quality_score', 0):.2f}")
            print(f"迭代次数: {data.get('iterations', 0)}")

            summary = data.get("summary", "")
            if summary:
                print(f"\n📄 摘要:")
                print(summary[:500] + "..." if len(summary) > 500 else summary)

        else:
            print(f"\n❌ 研究失败")
            print(f"错误: {result.get('error', '未知错误')}")

    except Exception as e:
        print(f"\n❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.disconnect()
        print("\n✅ MCP Client 已断开")


async def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("🚀 DeepResearch Skill 实际功能测试")
    print("=" * 60)

    # 测试1: 直接调用 Skill
    print("\n【测试 1】直接调用 DeepResearchSkill")
    await test_quick_research_real()

    # 测试2: 通过 MCP Client 调用
    print("\n\n【测试 2】通过 MCP Client 调用")
    await test_mcp_client_real()

    print("\n" + "=" * 60)
    print("✅ 所有实际功能测试完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
