#!/usr/bin/env python3
"""直接测试 MCP Server 的 STDIO 通信"""
import asyncio
import subprocess
import sys
import os
import json

async def test_stdio():
    # 设置环境变量
    os.environ["TUSHARE_API_TOKEN"] = "9e4123cf56aaa553b06556e64b05e9d8d004340d82897eb1704ccd91c088"
    os.environ["TUSHARE_API_URL"] = "http://lianghua.nanyangqiankun.top"

    server_path = "/Users/talantan/.openclaw/workspace-dev/external/financial-research-assistant/backend/app/mcp_server/server.py"

    print("=" * 60)
    print("启动 MCP Server 进程...")
    print("=" * 60)

    process = subprocess.Popen(
        [sys.executable, server_path],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=os.environ.copy(),
        bufsize=0  # 无缓冲
    )

    # 等待几秒让 Server 启动
    print("等待 Server 启动 (3秒)...")
    await asyncio.sleep(3)

    # 检查进程是否还在运行
    if process.poll() is not None:
        print(f"❌ Server 进程已退出，退出码: {process.returncode}")
        stderr = process.stderr.read().decode()
        print(f"STDERR:\n{stderr}")
        return

    print("✓ Server 进程正在运行")

    # 发送初始化请求
    init_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"}
        }
    }

    request_line = json.dumps(init_request) + "\n"
    print(f"\n发送请求 ({len(request_line)} bytes):")
    print(request_line.strip())
    print()

    try:
        process.stdin.write(request_line.encode())
        process.stdin.flush()
        print("✓ 请求已发送")
    except Exception as e:
        print(f"❌ 发送请求失败: {e}")
        process.terminate()
        return

    # 读取响应
    print("\n等待响应 (10秒超时)...")
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(process.stdout.readline),
            timeout=10.0
        )

        print(f"\n✓ 收到响应 ({len(response)} bytes):")
        print(response.decode().strip())

        # 尝试解析为 JSON
        try:
            response_json = json.loads(response.decode())
            print("\n✓ JSON 解析成功:")
            print(json.dumps(response_json, indent=2, ensure_ascii=False))
        except json.JSONDecodeError as e:
            print(f"\n❌ JSON 解析失败: {e}")

    except asyncio.TimeoutError:
        print("\n❌ 读取响应超时 (10秒)")

        # 检查 stderr 是否有输出
        try:
            stderr = process.stderr.read(1024).decode()
            if stderr:
                print(f"\nSTDERR 输出:\n{stderr}")
        except:
            pass
    except Exception as e:
        print(f"\n❌ 读取响应失败: {e}")

    # 终止进程
    print("\n终止 Server 进程...")
    process.terminate()
    try:
        process.wait(timeout=2)
        print("✓ Server 进程已终止")
    except subprocess.TimeoutExpired:
        print("⚠ Server 进程未响应终止信号，强制杀死")
        process.kill()

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_stdio())
