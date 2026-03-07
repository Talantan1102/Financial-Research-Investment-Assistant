#!/usr/bin/env python3
"""
MCP Server 连接诊断脚本

用于诊断 MCP Server STDIO 连接问题
"""

import asyncio
import logging
import os
import sys
import subprocess
from pathlib import Path

# 配置详细日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_server_script_directly():
    """测试1: 直接运行 server.py 检查是否有错误"""
    print("\n" + "="*70)
    print("测试1: 直接运行 MCP Server 脚本")
    print("="*70)

    project_root = Path(__file__).parent.parent.parent.parent
    server_script = project_root / "backend/app/mcp_server/server.py"

    print(f"Server 脚本路径: {server_script}")
    print(f"脚本存在: {server_script.exists()}")

    if not server_script.exists():
        print("❌ Server 脚本不存在")
        return False

    print("\n尝试导入 server 模块...")
    try:
        # 添加路径
        sys.path.insert(0, str(project_root / "backend"))
        from app.mcp_server import server
        print("✅ Server 模块导入成功")

        # 尝试创建 server 实例
        print("\n尝试创建 Server 实例...")
        test_server = server.create_server()
        print(f"✅ Server 实例创建成功: {test_server}")
        return True

    except Exception as e:
        print(f"❌ 错误: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_mcp_client_connection():
    """测试2: 使用 MCP Client 连接"""
    print("\n" + "="*70)
    print("测试2: MCP Client 连接测试")
    print("="*70)

    try:
        from app.mcp_client.client import MCPClient

        project_root = Path(__file__).parent.parent.parent.parent
        server_script = project_root / "backend/app/mcp_server/server.py"

        print(f"创建 MCP Client...")
        print(f"  Server 脚本: {server_script}")
        print(f"  连接超时: 30.0s")

        client = MCPClient(
            server_script_path=str(server_script),
            python_executable="python3",
            connect_timeout=30.0,
            call_timeout=30.0
        )

        print("\n开始连接...")
        connected = await client.connect()

        if connected:
            print("✅ 连接成功!")

            print("\n获取工具列表...")
            tools_result = await client.list_tools()

            if tools_result.get("success"):
                tools = tools_result.get("tools", [])
                print(f"✅ 成功获取 {len(tools)} 个工具:")
                for tool in tools:
                    print(f"  - {tool['name']}: {tool['description']}")
            else:
                print(f"❌ 获取工具列表失败: {tools_result.get('error')}")

            await client.disconnect()
            return True
        else:
            print("❌ 连接失败")
            return False

    except ImportError as e:
        print(f"❌ 导入错误: {e}")
        return False
    except Exception as e:
        print(f"❌ 异常: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_stdio_communication():
    """测试3: 直接测试 STDIO 通信"""
    print("\n" + "="*70)
    print("测试3: STDIO 通信测试")
    print("="*70)

    try:
        project_root = Path(__file__).parent.parent.parent.parent
        server_script = project_root / "backend/app/mcp_server/server.py"

        print(f"启动 Server 进程: python3 {server_script}")

        # 启动 server 进程
        process = await asyncio.create_subprocess_exec(
            "python3",
            str(server_script),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(project_root / "backend")
        )

        print(f"✅ 进程已启动, PID: {process.pid}")

        # 等待一下看进程是否立即退出
        try:
            await asyncio.wait_for(process.wait(), timeout=2.0)
            print(f"❌ 进程意外退出，退出码: {process.returncode}")

            # 读取错误输出
            stderr_output = await process.stderr.read()
            if stderr_output:
                print(f"\nStderr 输出:")
                print(stderr_output.decode('utf-8'))

            return False
        except asyncio.TimeoutError:
            # 超时说明进程还在运行，这是好的
            print("✅ 进程正常运行中")

            # 发送 initialize 请求
            print("\n发送 initialize 请求...")
            init_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "test-client",
                        "version": "1.0.0"
                    }
                }
            }

            import json
            request_line = json.dumps(init_request) + "\n"
            process.stdin.write(request_line.encode('utf-8'))
            await process.stdin.drain()

            print("等待响应...")
            try:
                # 读取响应（带超时）
                response_line = await asyncio.wait_for(
                    process.stdout.readline(),
                    timeout=5.0
                )

                if response_line:
                    print(f"✅ 收到响应: {response_line.decode('utf-8')[:100]}...")
                    result = True
                else:
                    print("❌ 未收到响应")
                    result = False

            except asyncio.TimeoutError:
                print("❌ 响应超时")
                result = False

            # 终止进程
            print("\n终止进程...")
            process.terminate()
            await process.wait()

            return result

    except Exception as e:
        print(f"❌ 异常: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


async def check_dependencies():
    """检查依赖"""
    print("\n" + "="*70)
    print("检查依赖")
    print("="*70)

    # 检查 mcp 包
    try:
        import mcp
        print(f"✅ mcp 已安装: {mcp.__version__ if hasattr(mcp, '__version__') else 'unknown version'}")
    except ImportError:
        print("❌ mcp 未安装")
        return False

    # 检查 tushare
    try:
        import tushare
        print(f"✅ tushare 已安装")
    except ImportError:
        print("⚠️  tushare 未安装（可选）")

    # 检查环境变量
    token = os.getenv("TUSHARE_API_TOKEN")
    if token:
        print(f"✅ TUSHARE_API_TOKEN 已设置: {token[:10]}...")
    else:
        print("⚠️  TUSHARE_API_TOKEN 未设置")

    return True


async def main():
    """主函数"""
    print("\n" + "="*70)
    print("MCP Server 连接诊断")
    print("="*70)

    # 检查依赖
    if not await check_dependencies():
        print("\n❌ 依赖检查失败，无法继续")
        return

    # 测试1: 直接运行 server 脚本
    test1_passed = await test_server_script_directly()

    if not test1_passed:
        print("\n⚠️  Server 脚本测试失败，跳过后续测试")
        return

    # 测试2: MCP Client 连接
    test2_passed = await test_mcp_client_connection()

    if not test2_passed:
        print("\n⚠️  MCP Client 连接失败，尝试 STDIO 通信测试")

        # 测试3: STDIO 通信
        test3_passed = await test_stdio_communication()

        if not test3_passed:
            print("\n❌ 所有测试失败")
            print("\n可能的问题:")
            print("1. Server 脚本有语法错误或导入错误")
            print("2. MCP Server 未正确响应 initialize 请求")
            print("3. STDIO 通信协议不匹配")
            print("4. 环境变量或依赖配置问题")
            return

    print("\n" + "="*70)
    print("✅ 诊断完成")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
