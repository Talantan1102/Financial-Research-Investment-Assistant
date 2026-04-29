#!/usr/bin/env python3
"""DeepResearch Skill 使用示例

演示如何在金融研投项目中使用 DeepResearch Skill
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.mcp_client.client import MCPClient


async def example_1_quick_research():
    """
    示例1: 快速研究 - 了解某只股票的基本情况
    """
    print("\n" + "=" * 60)
    print("示例 1: 快速研究 - 茅台基本情况")
    print("=" * 60)

    # 连接 MCP Server
    client = MCPClient()
    await client.connect()

    # 调用快速研究工具
    result = await client.call_tool(
        "deep_research.quick_research",
        {
            "query": "贵州茅台2024年投资价值分析，包括股价表现、财务指标、市场地位",
            "max_iterations": 3,
        },
    )

    if result["success"]:
        data = result["data"]
        print("\n📊 研究结果:")
        print(f"质量评分: {data.get('quality_score', 0):.2f}")
        print(f"迭代次数: {data.get('iterations', 0)}")
        print("\n📝 摘要:")
        print(data.get("summary", "无摘要"))
        print("\n💡 核心发现:")
        for fact in data.get("key_facts", [])[:3]:
            print(f"  - {fact.get('content', '')}")
        print("\n🔍 关键洞察:")
        for insight in data.get("key_insights", []):
            print(f"  - {insight}")
    else:
        print(f"❌ 研究失败: {result.get('error')}")

    await client.disconnect()


async def example_2_deep_research():
    """
    示例2: 深度研究 - 完整的行业或公司分析
    """
    print("\n" + "=" * 60)
    print("示例 2: 深度研究 - 新能源汽车行业分析")
    print("=" * 60)

    client = MCPClient()
    await client.connect()

    # 调用深度研究工具
    result = await client.call_tool(
        "deep_research.research_sync",
        {
            "query": "中国新能源汽车行业2024年发展现状与趋势，包括市场规模、主要玩家、竞争格局",
            "search_web": True,
        },
    )

    if result["success"]:
        data = result["data"]
        print("\n📊 研究结果:")
        print(f"会话ID: {data.get('session_id', '')}")
        print(f"质量评分: {data.get('quality_score', 0):.2f}")
        print(f"迭代次数: {data.get('iterations', 0)}")
        print("\n📄 报告预览:")
        report = data.get("final_report", "")
        print(report[:300] + "..." if len(report) > 300 else report)
        print(f"\n📈 数据点数量: {len(data.get('data_points', []))}")
        print(f"📚 参考来源数量: {len(data.get('references', []))}")
        print(f"💡 洞察数量: {len(data.get('insights', []))}")
    else:
        print(f"❌ 研究失败: {result.get('error')}")

    await client.disconnect()


async def example_3_with_qwen():
    """
    示例3: 结合 qwen function calling - LLM 自主选择工具
    """
    print("\n" + "=" * 60)
    print("示例 3: qwen 自主选择工具进行研究")
    print("=" * 60)

    from app.service.mcp_chat_service import mcp_chat

    # qwen 会自动判断是否需要使用 deep_research 工具
    answer = await mcp_chat("帮我深入研究一下比亚迪和特斯拉的竞争格局，分析各自的优势和劣势")

    print("\n🤖 qwen 的回答:")
    print(answer)


async def main():
    """主函数"""
    print("\n🎯 DeepResearch Skill 使用示例")
    print("=" * 60)

    # 检查环境变量
    if not os.environ.get("DASHSCOPE_API_KEY"):
        print("\n⚠️  警告: 未配置 DASHSCOPE_API_KEY")
        print("某些示例可能无法运行。请设置环境变量：")
        print("export DASHSCOPE_API_KEY='your_api_key'")
        return

    # 运行示例
    choice = input("\n选择要运行的示例 (1/2/3 或 all): ").strip()

    if choice == "1" or choice == "all":
        await example_1_quick_research()

    if choice == "2" or choice == "all":
        await example_2_deep_research()

    if choice == "3" or choice == "all":
        await example_3_with_qwen()

    if choice not in ["1", "2", "3", "all"]:
        print("\n示例说明:")
        print("1 - 快速研究（适合快速了解某个主题）")
        print("2 - 深度研究（适合完整的行业/公司分析）")
        print("3 - qwen 自主调用（LLM 智能选择工具）")
        print("all - 运行所有示例")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 示例已中断")
    except Exception as e:
        print(f"\n❌ 示例运行失败: {e}")
        import traceback

        traceback.print_exc()
