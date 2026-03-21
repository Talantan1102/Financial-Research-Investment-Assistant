#!/usr/bin/env python3
"""
金融研投助手 - LLM 驱动控制流测试

测试 LLM 是否能正确编排复杂任务
"""

import json
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend', 'app'))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', 'backend', '.env'))
except ImportError:
    pass

from app.service.mcp_chat_service import MCPChatService


async def test_llm_driven_analysis():
    """测试 LLM 驱动的综合分析"""
    print("\n🧠 测试: LLM 驱动的综合分析")
    
    # 指定正确的 server 路径
    server_path = os.path.join(
        os.path.dirname(__file__), '..', 'backend', 'app', 'mcp_server', 'server.py'
    )
    
    service = MCPChatService(
        model="qwen-max",
        mcp_server_path=server_path
    )
    await service.connect()
    
    try:
        # 复杂问题，需要多工具协作
        questions = [
            "分析一下茅台的股票，包括当前价格、估值水平、财务指标和风险评估",  # 需要4个工具
            "对比茅台和五粮液的估值和财务状况",  # 需要批量查询
            "如果茅台PE超过30倍，分析一下估值风险",  # 需要条件判断
        ]
        
        for q in questions:
            print(f"\n  问题: {q}")
            answer = await service.chat(q)
            print(f"  回答: {answer[:200]}...")
            print(f"  ✅ 完成\n")
            
    finally:
        await service.disconnect()


async def main():
    print("="*70)
    print("🧠 LLM 驱动控制流测试")
    print("="*70)
    
    await test_llm_driven_analysis()
    
    print("\n✅ 测试完成")


if __name__ == '__main__':
    asyncio.run(main())
