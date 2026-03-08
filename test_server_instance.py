#!/usr/bin/env python3
"""
测试 MCP Server 实例化
"""

import sys
import os

# 设置环境变量
os.environ["TUSHARE_API_TOKEN"] = "9e4123cf56aaa553b06556e64b05e9d8d004340d82897eb1704ccd91c088"
os.environ["TUSHARE_API_URL"] = "http://lianghua.nanyangqiankun.top"

# 添加路径
sys.path.insert(0, "backend")

print("=" * 80)
print("🧪 测试 MCP Server 实例化")
print("=" * 80)
print()

try:
    print("1️⃣ 导入模块...")
    from app.mcp_server.server import create_server
    print("✅ 模块导入成功")
    print()

    print("2️⃣ 创建 Server 实例...")
    server = create_server()
    print("✅ Server 实例创建成功")
    print()

    print("3️⃣ 检查已注册的 Skills...")
    for skill_name, skill in server.skills.items():
        print(f"  ✅ {skill_name}: {skill.tool_count} 个工具")
        for tool_def in skill.discover_tools():
            print(f"     • {tool_def.name}: {tool_def.description}")
    print()

    print("=" * 80)
    print("✅ 测试通过！Server 可以正常实例化")
    print("=" * 80)

except ImportError as e:
    print(f"❌ 导入错误: {e}")
    import traceback
    traceback.print_exc()
except Exception as e:
    print(f"❌ 创建失败: {e}")
    import traceback
    traceback.print_exc()
