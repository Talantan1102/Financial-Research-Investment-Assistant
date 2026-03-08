#!/usr/bin/env python3
"""
测试 MCP Chat Service

验证服务能否正常工作
"""

import asyncio
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.service.mcp_chat_service import MCPChatService, mcp_chat


async def test_service():
    """测试 MCP Chat Service"""
    print("=" * 80)
    print("🧪 测试 MCP Chat Service")
    print("=" * 80)
    print()

    try:
        # 方式 1: 使用上下文管理器
        print("方式 1: 使用上下文管理器")
        print("-" * 80)
        async with MCPChatService(model="qwen-max") as service:
            question = "查一下茅台近期的股市表现，值不值得买"
            print(f"问题: {question}")
            print()

            answer = await service.chat(question)
            print("回答:")
            print(answer)
            print()

        print("=" * 80)
        print()

        # 方式 2: 使用便捷函数
        print("方式 2: 使用便捷函数")
        print("-" * 80)
        question = "分析一下平安银行的财务状况"
        print(f"问题: {question}")
        print()

        answer = await mcp_chat(question, model="qwen-max")
        print("回答:")
        print(answer)
        print()

        print("=" * 80)
        print("✅ 测试通过！")
        print("=" * 80)

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_service())
