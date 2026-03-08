#!/usr/bin/env python3
"""DeepResearch Skill 功能测试

测试 DeepResearch Skill 的各项功能，包括：
1. 工具注册和发现
2. 参数验证
3. 错误处理
4. 与 MCP Server 集成
"""

import asyncio
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.mcp_server.skills.deep_research import DeepResearchSkill
from app.mcp_client.client import MCPClient


async def test_1_skill_initialization():
    """测试1: Skill 初始化"""
    print("\n" + "=" * 60)
    print("测试 1: Skill 初始化")
    print("=" * 60)

    try:
        skill = DeepResearchSkill()
        print(f"✅ Skill 创建成功")
        print(f"   名称: {skill.name}")
        print(f"   描述: {skill.description}")
        print(f"   工具数量: {skill.tool_count}")
        return True
    except Exception as e:
        print(f"❌ Skill 创建失败: {e}")
        return False


async def test_2_tool_discovery():
    """测试2: 工具发现"""
    print("\n" + "=" * 60)
    print("测试 2: 工具发现")
    print("=" * 60)

    try:
        skill = DeepResearchSkill()
        tools = skill.discover_tools()

        print(f"✅ 发现 {len(tools)} 个工具:\n")

        for tool in tools:
            print(f"📌 {tool.name}")
            print(f"   描述: {tool.description[:80]}...")
            print(f"   参数数量: {len(tool.parameters)}")

            # 检查必填参数
            required_params = [p for p in tool.parameters if p.required]
            print(f"   必填参数: {', '.join(p.name for p in required_params)}")

            # 检查可选参数
            optional_params = [p for p in tool.parameters if not p.required]
            if optional_params:
                print(f"   可选参数: {', '.join(p.name for p in optional_params)}")
            print()

        return True
    except Exception as e:
        print(f"❌ 工具发现失败: {e}")
        return False


async def test_3_parameter_validation():
    """测试3: 参数验证"""
    print("\n" + "=" * 60)
    print("测试 3: 参数验证")
    print("=" * 60)

    skill = DeepResearchSkill()

    # 测试缺少必填参数
    print("\n3.1 测试缺少必填参数...")
    result = await skill.execute_tool("quick_research", {})
    if not result.success:
        print(f"✅ 正确拒绝: {result.error}")
    else:
        print(f"❌ 应该拒绝但通过了")

    # 测试错误的参数类型
    print("\n3.2 测试错误的参数类型...")
    result = await skill.execute_tool("quick_research", {
        "query": 123,  # 应该是 string
        "max_iterations": "abc"  # 应该是 integer
    })
    if not result.success:
        print(f"✅ 正确拒绝: {result.error}")
    else:
        print(f"❌ 应该拒绝但通过了")

    # 测试正确的参数
    print("\n3.3 测试正确的参数格式...")
    print("   (不实际执行，只验证参数)")
    params = {
        "query": "测试问题",
        "max_iterations": 2
    }
    tool_def = skill._tool_definitions["quick_research"]
    error = skill._validate_params(params, tool_def)
    if error is None:
        print(f"✅ 参数验证通过")
    else:
        print(f"❌ 参数验证失败: {error}")

    return True


async def test_4_mcp_integration():
    """测试4: MCP Server 集成"""
    print("\n" + "=" * 60)
    print("测试 4: MCP Server 集成")
    print("=" * 60)

    try:
        # 创建 MCP Server
        from app.mcp_server.server import create_server
        server = create_server()

        print(f"✅ MCP Server 创建成功")
        print(f"   已注册 Skill 数量: {len(server.skills)}")

        # 检查 deep_research skill 是否注册
        if "deep_research" in server.skills:
            print(f"✅ deep_research Skill 已注册")
            skill = server.skills["deep_research"]
            print(f"   工具数量: {skill.tool_count}")
        else:
            print(f"❌ deep_research Skill 未注册")
            return False

        return True
    except Exception as e:
        print(f"❌ MCP Server 集成测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_5_mcp_client_call():
    """测试5: 通过 MCP Client 调用"""
    print("\n" + "=" * 60)
    print("测试 5: 通过 MCP Client 调用")
    print("=" * 60)

    try:
        # 启动 MCP Server（在后台）
        print("启动 MCP Server...")

        # 连接 MCP Client
        server_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "app/mcp_server/server.py"
        )

        client = MCPClient(server_script_path=server_path)
        await client.connect()
        print("✅ MCP Client 连接成功")

        # 列出工具
        result = await client.list_tools()
        if result.get("success"):
            tools = result["tools"]
            deep_research_tools = [t for t in tools if t["name"].startswith("deep_research.")]
            print(f"✅ 发现 {len(deep_research_tools)} 个 deep_research 工具:")
            for tool in deep_research_tools:
                print(f"   - {tool['name']}")
        else:
            print(f"❌ 列出工具失败: {result.get('error')}")
            return False

        # 测试调用（不需要真实 API key，只测试参数验证）
        print("\n测试工具调用（参数验证）...")
        result = await client.call_tool("deep_research.quick_research", {})
        if not result.get("success"):
            print(f"✅ 正确拒绝缺少参数: {result.get('error')}")
        else:
            print(f"❌ 应该拒绝但通过了")

        await client.disconnect()
        print("✅ MCP Client 断开连接")

        return True
    except Exception as e:
        print(f"❌ MCP Client 调用测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_6_tool_schema():
    """测试6: 工具 Schema 格式"""
    print("\n" + "=" * 60)
    print("测试 6: 工具 Schema 格式")
    print("=" * 60)

    try:
        skill = DeepResearchSkill()
        tools_json = skill.discover_tools_json()

        print(f"✅ 生成 {len(tools_json)} 个工具的 JSON Schema\n")

        for tool_schema in tools_json:
            print(f"📌 {tool_schema['name']}")
            print(f"   Schema 结构:")
            print(f"   - name: {tool_schema.get('name')}")
            print(f"   - description: {tool_schema.get('description')[:50]}...")
            print(f"   - parameters.type: {tool_schema.get('parameters', {}).get('type')}")
            print(f"   - parameters.properties: {len(tool_schema.get('parameters', {}).get('properties', {}))} 个")
            print(f"   - parameters.required: {tool_schema.get('parameters', {}).get('required', [])}")
            print()

        # 验证 Schema 格式
        for tool_schema in tools_json:
            assert "name" in tool_schema, "缺少 name 字段"
            assert "description" in tool_schema, "缺少 description 字段"
            assert "parameters" in tool_schema, "缺少 parameters 字段"
            assert tool_schema["parameters"]["type"] == "object", "parameters.type 应该是 object"

        print("✅ 所有 Schema 格式验证通过")
        return True
    except Exception as e:
        print(f"❌ Schema 格式验证失败: {e}")
        return False


async def test_7_error_handling():
    """测试7: 错误处理"""
    print("\n" + "=" * 60)
    print("测试 7: 错误处理")
    print("=" * 60)

    skill = DeepResearchSkill()

    # 测试调用不存在的工具
    print("\n7.1 测试调用不存在的工具...")
    result = await skill.execute_tool("non_existent_tool", {"query": "test"})
    if not result.success:
        print(f"✅ 正确处理: {result.error}")
    else:
        print(f"❌ 应该返回错误")

    # 测试空参数
    print("\n7.2 测试空参数...")
    result = await skill.execute_tool("quick_research", {})
    if not result.success:
        print(f"✅ 正确处理: {result.error}")
    else:
        print(f"❌ 应该返回错误")

    return True


async def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("🧪 DeepResearch Skill 功能测试")
    print("=" * 60)

    tests = [
        ("Skill 初始化", test_1_skill_initialization),
        ("工具发现", test_2_tool_discovery),
        ("参数验证", test_3_parameter_validation),
        ("MCP Server 集成", test_4_mcp_integration),
        ("MCP Client 调用", test_5_mcp_client_call),
        ("工具 Schema 格式", test_6_tool_schema),
        ("错误处理", test_7_error_handling),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = await test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ 测试 '{name}' 异常: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    # 打印测试总结
    print("\n" + "=" * 60)
    print("📊 测试总结")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{status} - {name}")

    print("\n" + "=" * 60)
    print(f"总计: {passed}/{total} 测试通过")
    print("=" * 60)

    if passed == total:
        print("\n🎉 所有测试通过！")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
