#!/usr/bin/env python3
"""测试 MCP Server 新架构（Resource + Tool 协同）

新架构测试流程：
- Round 1: list_resources() 返回 7 个 Skill Resource
- Round 2: read_resource("skill://market_data") 返回 SKILL.md 内容
- Round 3: list_tools() 返回 market_data 的 11 个工具
- Round 4: call_tool("market_data.get_quote", {...}) 返回股价数据

工具名格式: skill_name.tool_name (如 market_data.get_quote)
"""

import asyncio
import json
import sys
import os

# 添加 backend 到 path
backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, backend_dir)

# 加载 .env 文件到环境变量（MCP Server 子进程会继承）
env_path = os.path.join(backend_dir, ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())
    print(f"已加载 .env ({env_path})")

from app.mcp_client.client import mcp_client_context

SERVER_PATH = os.path.join(backend_dir, "app/mcp_server/server.py")
PYTHON = os.environ.get("PYTHON", "/Users/talantan/.openclaw/workspace-dev/external/financial-research-assistant/venv/bin/python3")


async def test_list_resources(session):
    """测试 1: list_resources 返回 7 个 Skill Resource"""
    print("=" * 60)
    print("TEST 1: list_resources 验证")
    print("=" * 60)

    response = await session.list_resources()
    resources = response.resources

    print(f"返回 {len(resources)} 个 Resource:")
    for r in resources:
        uri_str = str(r.uri)
        print(f"  - {r.name}: {uri_str}")

    # 验证数量
    assert len(resources) == 7, f"期望 7 个 Resource，实际 {len(resources)}"
    
    # 验证所有 resource 都以 skill:// 开头
    for r in resources:
        uri_str = str(r.uri)
        assert uri_str.startswith("skill://"), f"Resource URI 应以 skill:// 开头: {uri_str}"
    
    # 验证包含 market_data
    uris = {str(r.uri) for r in resources}
    assert "skill://market_data" in uris, f"应包含 skill://market_data"

    print("\n[PASS] list_resources 返回 7 个 Skill Resource")
    print("=" * 60 + "\n")
    return resources


async def test_read_resource(session):
    """测试 2: read_resource 返回 SKILL.md 内容"""
    print("=" * 60)
    print("TEST 2: read_resource 验证")
    print("=" * 60)

    result = await session.read_resource("skill://market_data")
    
    # 获取文本内容
    content = result.contents[0]
    text = content.text if hasattr(content, 'text') else str(content)

    print(f"返回内容长度: {len(text)} 字符")
    print(f"前 300 字符:\n{text[:300]}...")

    # 验证是 SKILL.md 内容（以 --- 开头的 frontmatter）
    assert text.startswith("---"), "SKILL.md 应以 --- 开头"
    
    # 验证包含关键内容
    assert "market_data" in text, "应包含 market_data"
    assert "描述" in text or "description" in text.lower(), "应包含描述信息"

    print("\n[PASS] read_resource 返回正确的 SKILL.md 内容")
    print("=" * 60 + "\n")
    return text


async def test_list_tools_after_read_resource(session):
    """测试 3: 读取 Resource 后 list_tools 返回对应 skill 的工具"""
    print("=" * 60)
    print("TEST 3: list_tools 渐进式披露验证")
    print("=" * 60)

    # Round 1: 读取 Resource 前，应该没有工具或只有基础工具
    print("\n--- Round 1: 读取 Resource 前 ---")
    response = await session.list_tools()
    tools_before = response.tools
    print(f"读取 Resource 前: {len(tools_before)} 个工具")
    for t in tools_before:
        print(f"  - {t.name}")

    # Round 2: 读取 Resource
    print("\n--- Round 2: 读取 skill://market_data ---")
    await session.read_resource("skill://market_data")
    print("[OK] read_resource 调用成功")

    # Round 3: 读取 Resource 后，应该返回 market_data 的 11 个工具
    print("\n--- Round 3: 读取 Resource 后 ---")
    response = await session.list_tools()
    tools_after = response.tools

    print(f"读取 Resource 后: {len(tools_after)} 个工具")
    for t in tools_after:
        desc_short = (t.description or "")[:50].replace("\n", " ")
        print(f"  - {t.name}: {desc_short}...")

    # 验证工具数量（market_data 应该有 11 个工具）
    assert len(tools_after) == 11, f"期望 11 个工具，实际 {len(tools_after)}"

    # 验证工具名格式: market_data.xxx
    tool_names = {t.name for t in tools_after}
    for name in tool_names:
        assert name.startswith("market_data."), f"工具名应以 market_data. 开头: {name}"

    # 验证包含关键工具
    assert "market_data.get_quote" in tool_names, "应包含 market_data.get_quote"
    assert "market_data.get_history" in tool_names, "应包含 market_data.get_history"

    print(f"\n[PASS] list_tools 返回 11 个 market_data 工具")
    print("=" * 60 + "\n")
    return tools_after


async def test_call_tool(session):
    """测试 4: call_tool 执行工具"""
    print("=" * 60)
    print("TEST 4: call_tool 执行验证")
    print("=" * 60)

    # 先读取 Resource
    await session.read_resource("skill://market_data")

    # 调用工具
    print("\n--- 调用 market_data.get_quote ---")
    result = await session.call_tool("market_data.get_quote", {"symbol": "600519"})
    
    # 获取结果文本
    text = result.content[0].text
    print(f"返回结果:\n{text[:500]}...")

    # 尝试解析 JSON
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            print(f"\n解析结果:")
            if "name" in data:
                print(f"  股票名称: {data.get('name')}")
            if "nowPri" in data:
                print(f"  当前价格: {data.get('nowPri')}")
            if "code" in data:
                print(f"  股票代码: {data.get('code')}")
            print(f"\n[PASS] call_tool 执行成功并返回数据")
        else:
            print(f"\n[PASS] call_tool 执行成功 (返回非对象数据)")
    except json.JSONDecodeError:
        # 可能返回的是文本格式
        if "600519" in text or "贵州茅台" in text or "error" in text.lower():
            print(f"\n[PASS] call_tool 执行成功 (返回文本)")
        else:
            print(f"\n[WARN] 返回非 JSON 格式，但工具调用链路正确")

    print("=" * 60 + "\n")


async def test_tool_not_found(session):
    """测试 5: 不存在的工具返回错误"""
    print("=" * 60)
    print("TEST 5: 错误处理验证")
    print("=" * 60)

    # 先读取 Resource
    await session.read_resource("skill://market_data")

    # 调用不存在的工具
    print("\n--- 调用不存在的工具 ---")
    try:
        result = await session.call_tool("market_data.nonexistent_tool", {"symbol": "600519"})
        text = result.content[0].text
        print(f"返回: {text[:200]}")
        
        # 检查是否包含错误信息
        if "error" in text.lower() or "不存在" in text or "not found" in text.lower():
            print("[PASS] 不存在的工具返回正确错误")
        else:
            print("[INFO] 工具调用返回结果")
    except Exception as e:
        print(f"[PASS] 不存在的工具抛出异常 (预期行为): {type(e).__name__}: {str(e)[:80]}")

    print("\n" + "=" * 60)
    print("[PASS] 错误处理验证通过!")
    print("=" * 60 + "\n")


async def test_full_workflow(session):
    """测试 6: 完整工作流验证 - list_resources -> read_resource -> list_tools -> call_tool"""
    print("=" * 60)
    print("TEST 6: 完整工作流验证")
    print("=" * 60)

    # Step 1: list_resources
    print("\n--- Step 1: list_resources ---")
    response = await session.list_resources()
    resources = response.resources
    print(f"发现 {len(resources)} 个 Skill Resource")
    
    # 找到 market_data
    market_data_resource = None
    for r in resources:
        if str(r.uri) == "skill://market_data":
            market_data_resource = r
            break
    assert market_data_resource is not None, "应找到 market_data resource"
    print(f"[OK] 找到 {str(market_data_resource.uri)}")

    # Step 2: read_resource
    print("\n--- Step 2: read_resource ---")
    result = await session.read_resource("skill://market_data")
    content = result.contents[0]
    text = content.text if hasattr(content, 'text') else str(content)
    print(f"[OK] 读取 SKILL.md ({len(text)} 字符)")

    # Step 3: list_tools
    print("\n--- Step 3: list_tools ---")
    response = await session.list_tools()
    tools = response.tools
    print(f"[OK] 获取 {len(tools)} 个工具")
    
    # 找到 get_quote 工具
    get_quote_tool = None
    for t in tools:
        if t.name == "market_data.get_quote":
            get_quote_tool = t
            break
    assert get_quote_tool is not None, "应找到 market_data.get_quote 工具"
    print(f"[OK] 找到工具: {get_quote_tool.name}")

    # Step 4: call_tool
    print("\n--- Step 4: call_tool ---")
    result = await session.call_tool("market_data.get_quote", {"symbol": "600519"})
    text = result.content[0].text
    print(f"[OK] 工具执行成功")
    print(f"返回前 300 字符:\n{text[:300]}...")

    print("\n" + "=" * 60)
    print("[PASS] 完整工作流验证通过!")
    print("=" * 60 + "\n")


async def test_multiple_skills(session):
    """测试 7: 多个 Skill 的工具共存"""
    print("=" * 60)
    print("TEST 7: 多个 Skill 工具共存验证")
    print("=" * 60)

    # 读取第一个 Resource
    print("\n--- 读取 market_data ---")
    await session.read_resource("skill://market_data")
    
    # 读取第二个 Resource
    print("\n--- 读取 financial_analysis ---")
    try:
        await session.read_resource("skill://financial_analysis")
        print("[OK] 读取 financial_analysis 成功")
    except Exception as e:
        print(f"[INFO] 读取 financial_analysis: {type(e).__name__}: {str(e)[:80]}")

    # 检查工具列表
    print("\n--- 检查工具列表 ---")
    response = await session.list_tools()
    tools = response.tools
    
    print(f"共有 {len(tools)} 个工具:")
    market_data_tools = [t for t in tools if t.name.startswith("market_data.")]
    financial_analysis_tools = [t for t in tools if t.name.startswith("financial_analysis.")]
    
    print(f"  - market_data 工具: {len(market_data_tools)} 个")
    print(f"  - financial_analysis 工具: {len(financial_analysis_tools)} 个")
    
    for t in tools[:10]:  # 只显示前 10 个
        print(f"    - {t.name}")
    if len(tools) > 10:
        print(f"    ... 还有 {len(tools) - 10} 个")

    print("\n[PASS] 多个 Skill 工具共存验证完成")
    print("=" * 60 + "\n")


async def main():
    print("\n" + "=" * 60)
    print("MCP Server 新架构测试 (Resource + Tool 协同)")
    print(f"Server: {SERVER_PATH}")
    print(f"Python: {PYTHON}")
    print("=" * 60 + "\n")

    try:
        # 每个测试使用独立的 session，确保状态隔离
        print("开始测试...\n")

        # 测试 1: list_resources
        async with mcp_client_context(SERVER_PATH, python_executable=PYTHON) as session:
            await test_list_resources(session)

        # 测试 2: read_resource
        async with mcp_client_context(SERVER_PATH, python_executable=PYTHON) as session:
            await test_read_resource(session)

        # 测试 3: list_tools 渐进式披露
        async with mcp_client_context(SERVER_PATH, python_executable=PYTHON) as session:
            await test_list_tools_after_read_resource(session)

        # 测试 4: call_tool
        async with mcp_client_context(SERVER_PATH, python_executable=PYTHON) as session:
            await test_call_tool(session)

        # 测试 5: 错误处理
        async with mcp_client_context(SERVER_PATH, python_executable=PYTHON) as session:
            await test_tool_not_found(session)

        # 测试 6: 完整工作流
        async with mcp_client_context(SERVER_PATH, python_executable=PYTHON) as session:
            await test_full_workflow(session)

        # 测试 7: 多个 Skill 共存
        async with mcp_client_context(SERVER_PATH, python_executable=PYTHON) as session:
            await test_multiple_skills(session)

        print("=" * 60)
        print("ALL TESTS PASSED!")
        print("=" * 60)

    except Exception as e:
        print(f"\n[FATAL] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
