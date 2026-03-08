#!/usr/bin/env python3
"""
STDIO 连接调试脚本 - 使用新的上下文管理器方式
"""

import os
import sys
import asyncio

# 添加项目路径
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(PROJECT_ROOT)))
sys.path.insert(0, BACKEND_DIR)

from app.mcp_client.client import mcp_client_context

async def test_stdio_connection():
    """测试 STDIO 连接"""
    print("=" * 80)
    print("🔍 STDIO 连接诊断 (使用上下文管理器)")
    print("=" * 80)

    server_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "server.py"
    )

    print(f"\n1️⃣  Server 路径: {server_path}")
    print(f"   文件存在: {os.path.exists(server_path)}")

    try:
        print("\n2️⃣  使用 mcp_client_context 连接...")
        
        async with mcp_client_context(server_path, connect_timeout=15.0) as session:
            print("✅ 连接成功！")
            
            print("\n3️⃣  列出工具...")
            tools_result = await session.list_tools()
            print(f"✅ 成功列出 {len(tools_result.tools)} 个工具")
            for tool in tools_result.tools:
                print(f"   • {tool.name}")
            
            print("\n4️⃣  测试调用 get_quote...")
            result = await session.call_tool(
                "market_data.get_quote",
                {"symbol": "600519"}
            )
            print(f"✅ 调用成功！")
            if result.content:
                import json
                data = json.loads(result.content[0].text)
                print(f"   数据: {data.get('data', {})}")
            
            return True

    except FileNotFoundError as e:
        print(f"\n❌ 文件错误: {e}")
        return False
    except asyncio.TimeoutError:
        print("\n❌ 连接超时")
        return False
    except Exception as e:
        print(f"\n❌ 错误: {type(e).__name__}: {e}")
        import traceback
        print("\n详细堆栈:")
        print(traceback.format_exc())
        return False

async def main():
    success = await test_stdio_connection()

    print("\n" + "=" * 80)
    if success:
        print("✅ 诊断成功：MCP STDIO 通信正常")
    else:
        print("❌ 诊断失败：MCP STDIO 通信存在问题")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())
