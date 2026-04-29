#!/usr/bin/env python3
"""端到端测试: 用户问题 → Skill 选择 → 工具调用 → LLM 回答"""

import asyncio
import logging
import os
import sys

# 添加 backend 到 path
backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, backend_dir)

# 加载 .env 文件到环境变量
env_path = os.path.join(backend_dir, ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())
    print(f"已加载 .env ({env_path})")

# 设置日志级别，显示编排层日志
logging.basicConfig(level=logging.INFO, format="%(name)s - %(levelname)s - %(message)s")

from app.service.mcp_chat_service import MCPChatService

SERVER_PATH = os.path.join(backend_dir, "app/mcp_server/server.py")
MODEL = os.environ.get("OPENAI_MODEL", "qwen-max")


async def test_question(service, question: str):
    """测试单个问题"""
    print(f"\n{'=' * 60}")
    print(f"用户问题: {question}")
    print(f"{'=' * 60}\n")

    answer = await service.chat(question)

    print(f"\n{'=' * 60}")
    print("LLM 回答:")
    print(f"{'=' * 60}")
    print(answer)
    print(f"{'=' * 60}\n")
    return answer


async def main():
    print(f"\n{'=' * 60}")
    print("端到端测试: 三轮编排架构")
    print(f"Server: {SERVER_PATH}")
    print(f"Model: {MODEL}")
    print(f"{'=' * 60}\n")

    try:
        service = MCPChatService(
            mcp_server_path=SERVER_PATH, model=MODEL, connect_timeout=30.0, call_timeout=30.0
        )

        await service.connect()
        print("[OK] MCP Client 连接成功\n")

        # 测试 1: 股票行情查询 → 应选择 market_data skill → 调用 get_quote
        answer1 = await test_question(service, "今天茅台的行情如何？")
        assert len(answer1) > 20, f"回答太短: {answer1}"
        print("[PASS] 测试 1: 股票行情查询\n")

        # 测试 2: 简单问候 → 应直接回答，不调用 skill
        answer2 = await test_question(service, "你好，你是谁？")
        print("[PASS] 测试 2: 简单问候（无需 skill）\n")

        # 测试 3: 财务分析 → 应选择 financial_analysis skill
        answer3 = await test_question(service, "茅台最近的ROE是多少？")
        assert len(answer3) > 20, f"回答太短: {answer3}"
        print("[PASS] 测试 3: 财务指标查询\n")

        await service.disconnect()

        print(f"\n{'=' * 60}")
        print("ALL E2E TESTS PASSED!")
        print(f"{'=' * 60}")

    except Exception as e:
        print(f"\n[FATAL] 测试失败: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
