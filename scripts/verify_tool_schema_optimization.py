#!/usr/bin/env python3
"""
验证 Tool Schema 优化效果

检查:
1. 服务器是否正确隐藏了内部工具
2. 工具列表是否只包含 LLM 可调用的工具
3. 工具命名格式是否正确

用法:
    python scripts/verify_tool_schema_optimization.py
"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sandbox.tool_schemas import get_tool_schemas, ALL_SKILLS


def verify_tool_schemas():
    """验证 tool_schemas 模块"""
    print("=" * 80)
    print("验证 Tool Schemas")
    print("=" * 80)

    schemas = get_tool_schemas()
    tool_names = [s["function"]["name"] for s in schemas]

    print(f"\n总工具数量: {len(schemas)}")

    # 检查 Round 1 工具
    if "skill" in tool_names:
        print("✅ Round 1 工具 'skill' 存在")
    else:
        print("❌ Round 1 工具 'skill' 缺失")

    # 检查不应该存在的内部工具
    internal_tools = ["get_skill_tools", "execute_skill_tool", "select_skill"]
    found_internal = [t for t in internal_tools if t in tool_names]

    if found_internal:
        print(f"❌ 发现不应存在的内部工具: {found_internal}")
    else:
        print("✅ 内部工具已正确隐藏")

    # 检查 Round 2 工具格式
    round2_tools = [t for t in tool_names if "." in t]
    print(f"\nRound 2 工具数量: {len(round2_tools)}")

    # 检查每个 skill 至少有一个工具
    skills_with_tools = set(t.split(".")[0] for t in round2_tools)
    missing_skills = set(ALL_SKILLS.keys()) - skills_with_tools

    if missing_skills:
        print(f"⚠️  缺少工具的技能: {missing_skills}")
    else:
        print(f"✅ 所有 {len(ALL_SKILLS)} 个 skills 都有工具")

    # 打印部分工具示例
    print("\n工具示例:")
    for tool in round2_tools[:5]:
        print(f"  - {tool}")
    if len(round2_tools) > 5:
        print(f"  ... 还有 {len(round2_tools) - 5} 个工具")

    return len(found_internal) == 0


def verify_server_tools():
    """验证服务器返回的工具列表"""
    print("\n" + "=" * 80)
    print("验证服务器工具列表 (需要服务器运行)")
    print("=" * 80)

    try:
        from sandbox.sandbox import Sandbox

        async def check():
            sandbox = Sandbox(server_url="http://127.0.0.1:8080", auto_start_server=False)
            try:
                await sandbox.start()
                tools = await sandbox.client.list_tools(include_hidden=False)

                tool_names = []
                for t in tools:
                    if isinstance(t, dict):
                        name = t.get("full_name") or t.get("name")
                        if name:
                            tool_names.append(name)

                print(f"\n服务器返回工具数量: {len(tool_names)}")

                # 检查内部工具
                internal_tools = ["get_skill_tools", "execute_skill_tool", "select_skill"]
                found_internal = []

                for tool_name in tool_names:
                    base_name = tool_name.split(":")[-1]
                    if base_name in internal_tools:
                        found_internal.append(tool_name)

                if found_internal:
                    print(f"❌ 服务器暴露了内部工具: {found_internal}")
                    return False
                else:
                    print("✅ 服务器正确隐藏了内部工具")

                # 检查 skill 工具
                has_skill = any("skill" == t.split(":")[-1] for t in tool_names)
                if has_skill:
                    print("✅ 服务器包含 'skill' 工具")
                else:
                    print("❌ 服务器缺少 'skill' 工具")

                # 检查 Round 2 工具
                round2_count = sum(1 for t in tool_names if "." in t)
                print(f"✅ 服务器包含 {round2_count} 个 Round 2 工具")

                return True

            finally:
                await sandbox.close()

        import asyncio
        return asyncio.run(check())

    except Exception as e:
        print(f"⚠️  无法连接服务器: {e}")
        print("   请确保服务器正在运行: ./start_sandbox_server.sh")
        return None


def main():
    print("\n🔍 Tool Schema 优化验证\n")

    success = True

    # 验证 tool_schemas 模块
    if not verify_tool_schemas():
        success = False

    # 验证服务器 (如果可用)
    server_result = verify_server_tools()
    if server_result is False:
        success = False

    print("\n" + "=" * 80)
    if success:
        print("✅ 所有验证通过!")
    else:
        print("❌ 验证失败，请检查上述错误")
    print("=" * 80)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
