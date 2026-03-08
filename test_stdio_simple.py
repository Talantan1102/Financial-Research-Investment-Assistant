#!/usr/bin/env python3
"""
测试 STDIO 通信
"""

import asyncio
import json
import sys
import os

# 设置环境变量
os.environ["TUSHARE_API_TOKEN"] = "9e4123cf56aaa553b06556e64b05e9d8d004340d82897eb1704ccd91c088"
os.environ["TUSHARE_API_URL"] = "http://lianghua.nanyangqiankun.top"

# 添加路径
sys.path.insert(0, "backend")

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_stdio():
    """测试 STDIO 连接"""
    print("=" * 80)
    print("🔌 测试 STDIO 连接")
    print("=" * 80)
    print()

    server_path = os.path.abspath("backend/app/mcp_server/server.py")
    print(f"Server 路径: {server_path}")
    print(f"Server 存在: {os.path.exists(server_path)}")
    print()

    # 配置环境变量
    env_vars = os.environ.copy()
    backend_dir = os.path.dirname(os.path.dirname(server_path))
    project_root = os.path.dirname(backend_dir)

    env_vars['PYTHONPATH'] = backend_dir

    server_params = StdioServerParameters(
        command="python3",
        args=[server_path],
        env=env_vars,
        cwd=project_root
    )

    print(f"命令: python3 {server_path}")
    print(f"工作目录: {project_root}")
    print(f"PYTHONPATH: {env_vars['PYTHONPATH']}")
    print()

    print("🚀 启动 STDIO client...")

    try:
        async with stdio_client(server_params) as (read_stream, write_stream):
            print("✅ STDIO streams 创建成功")

            session = ClientSession(read_stream, write_stream)
            print("✅ Session 创建成功")

            print("\n🔄 正在初始化会话...")
            try:
                init_result = await asyncio.wait_for(
                    session.initialize(),
                    timeout=10.0
                )
                print(f"✅ 会话初始化成功!")
                print(f"   Server info: {init_result.server_info}")
                print(f"   Capabilities: {init_result.capabilities}")

                # 列出工具
                print("\n📋 列出可用工具...")
                tools_response = await session.list_tools()
                print(f"✅ 找到 {len(tools_response.tools)} 个工具")
                for tool in tools_response.tools[:3]:
                    print(f"   • {tool.name}: {tool.description[:50]}...")

            except asyncio.TimeoutError:
                print("❌ 会话初始化超时 (10秒)")
            except Exception as e:
                print(f"❌ 会话初始化失败: {e}")
                import traceback
                traceback.print_exc()

    except Exception as e:
        print(f"❌ STDIO client 创建失败: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 80)
    print("✅ 测试完成")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_stdio())
