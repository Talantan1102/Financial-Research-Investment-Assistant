#!/usr/bin/env python3
"""
直接测试 MCP Server 是否能启动
"""

import subprocess
import sys
import os

# 设置环境变量
env = os.environ.copy()
env["TUSHARE_API_TOKEN"] = "9e4123cf56aaa553b06556e64b05e9d8d004340d82897eb1704ccd91c088"
env["TUSHARE_API_URL"] = "http://lianghua.nanyangqiankun.top"

server_path = "backend/app/mcp_server/server.py"

print("=" * 80)
print("🚀 测试 MCP Server 是否能启动")
print("=" * 80)
print(f"Server 路径: {server_path}")
print(f"当前目录: {os.getcwd()}")
print()

print("启动 MCP Server (5秒后会自动停止)...")
print("-" * 80)

try:
    # 启动 server 并等待其输出
    proc = subprocess.Popen(
        [sys.executable, server_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True
    )

    # 等待5秒看输出
    try:
        stdout, stderr = proc.communicate(timeout=5)
        print("STDOUT:")
        print(stdout)
        print("\nSTDERR:")
        print(stderr)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        print("STDOUT (前5秒):")
        print(stdout)
        print("\nSTDERR (前5秒):")
        print(stderr)

except Exception as e:
    print(f"❌ 启动失败: {e}")
    import traceback
    traceback.print_exc()

print("-" * 80)
print("✅ 测试完成")
