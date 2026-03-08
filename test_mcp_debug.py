#!/usr/bin/env python3
"""
调试 MCP Client 连接问题
"""

import asyncio
import logging
import sys
import os
import traceback

# 添加路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

# 设置环境变量
os.environ["TUSHARE_API_TOKEN"] = "9e4123cf56aaa553b06556e64b05e9d8d004340d82897eb1704ccd91c088"
os.environ["TUSHARE_API_URL"] = "http://lianghua.nanyangqiankun.top"

# 配置更详细的日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from app.mcp_client.client import MCPClient


async def test_connection():
    """测试连接"""
    print("=" * 80)
    print("🔍 开始调试 MCP Client 连接...")
    print("=" * 80)

    server_path = os.path.join(
        os.path.dirname(__file__),
        "backend/app/mcp_server/server.py"
    )

    print(f"\n📂 Server 路径: {server_path}")
    print(f"✅ Server 文件存在: {os.path.exists(server_path)}")
    print(f"🔑 Tushare Token: {os.environ.get('TUSHARE_API_TOKEN', '未设置')[:20]}...")
    print(f"🌐 Tushare URL: {os.environ.get('TUSHARE_API_URL', '未设置')}")

    client = MCPClient(server_script_path=server_path)

    try:
        print("\n🔌 尝试连接...")
        connected = await client.connect()

        if connected:
            print("✅ 连接成功！")

            # 列出工具
            print("\n📋 列出可用工具...")
            tools_result = await client.list_tools()
            if tools_result.get("success"):
                tools = tools_result.get("tools", [])
                print(f"✅ 找到 {len(tools)} 个工具:")
                for tool in tools:
                    print(f"  • {tool['name']}")
            else:
                print(f"❌ 列出工具失败: {tools_result.get('error')}")
        else:
            print("❌ 连接失败")

    except Exception as e:
        print(f"\n❌ 发生异常:")
        print(f"异常类型: {type(e).__name__}")
        print(f"异常信息: {e}")
        print("\n完整堆栈:")
        traceback.print_exc()

        # 尝试获取更多异常信息
        if hasattr(e, '__cause__'):
            print(f"\n原因 (__cause__):")
            print(f"  类型: {type(e.__cause__).__name__}")
            print(f"  信息: {e.__cause__}")

        if hasattr(e, '__context__'):
            print(f"\n上下文 (__context__):")
            print(f"  类型: {type(e.__context__).__name__}")
            print(f"  信息: {e.__context__}")

        # 如果是 ExceptionGroup，展开所有异常
        if hasattr(e, 'exceptions'):
            print(f"\n子异常 (ExceptionGroup):")
            for i, sub_exc in enumerate(e.exceptions, 1):
                print(f"\n  子异常 {i}:")
                print(f"    类型: {type(sub_exc).__name__}")
                print(f"    信息: {sub_exc}")
                traceback.print_exception(type(sub_exc), sub_exc, sub_exc.__traceback__)

    finally:
        print("\n🧹 清理连接...")
        await client.disconnect()
        print("✅ 完成")


if __name__ == "__main__":
    asyncio.run(test_connection())
