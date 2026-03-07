#!/usr/bin/env python3
"""
最小化 MCP 测试脚本
用于诊断 MCP Server 连接问题

运行方式：
    python -m app.scripts.test_mcp_minimal
"""

import asyncio
import logging
import os
import sys
import time

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from app.mcp_client.client import MCPClient

# 配置日志 - 更详细的输出
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


async def test_basic_connection():
    """测试基本连接"""
    print("\n" + "="*80)
    print("MCP 最小化连接测试")
    print("="*80)

    # 获取 Server 脚本路径
    server_script_path = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "../mcp_server/server.py"
        )
    )

    print(f"\nServer 脚本路径: {server_script_path}")
    print(f"文件存在: {os.path.exists(server_script_path)}")

    # 测试 1: 尝试使用 python3 启动
    print("\n[测试 1] 使用 python3 连接")
    mcp_client = None
    try:
        mcp_client = MCPClient(
            server_script_path=server_script_path,
            python_executable="python3",
            connect_timeout=15.0,
            call_timeout=10.0
        )

        start_time = time.time()
        connected = await mcp_client.connect()
        duration = time.time() - start_time

        if connected:
            print(f"✅ 连接成功! ({duration:.2f}s)")

            # 测试 list_tools
            print("\n尝试列出工具...")
            tools_result = await mcp_client.list_tools()
            if tools_result.get("success"):
                tools = tools_result.get("tools", [])
                print(f"✅ 获取工具列表成功，共 {len(tools)} 个工具:")
                for tool in tools:
                    print(f"  - {tool['name']}: {tool.get('description', '')[:60]}...")
            else:
                print(f"❌ 获取工具列表失败: {tools_result.get('error')}")

        else:
            print(f"❌ 连接失败 ({duration:.2f}s)")
            return False

    except Exception as e:
        logger.error(f"测试异常: {type(e).__name__}: {e}", exc_info=True)
        return False
    finally:
        if mcp_client and mcp_client.is_connected:
            await mcp_client.disconnect()
            print("✅ 连接已断开")

    return True


async def test_with_mock():
    """使用 Mock 模式测试（如果 MCP 连接失败）"""
    print("\n" + "="*80)
    print("Mock 模式测试（降级测试）")
    print("="*80)

    from app.mcp_client.adapter import ToolAdapter

    # 创建不存在的 MCP Client（模拟连接失败）
    server_script_path = "/invalid/path/server.py"
    mcp_client = MCPClient(
        server_script_path=server_script_path,
        connect_timeout=2.0,
        call_timeout=2.0
    )

    # 不尝试连接
    print("\n[测试] ToolAdapter 降级模式")

    tool_adapter = ToolAdapter(
        mcp_client=mcp_client,
        fallback_enabled=True
    )

    print(f"使用 MCP: {tool_adapter.is_using_mcp}")
    print(f"已降级: {tool_adapter.is_degraded}")

    # 尝试调用（应该降级到 StockService）
    print("\n尝试获取股票数据 (600519)...")
    result = await tool_adapter.get_stock_by_code("600519")

    if result.get("success"):
        data = result.get("data", {})
        print(f"✅ 降级模式下获取成功: {data.get('name', 'N/A')}")
        print(f"   当前价: {data.get('nowPri', 'N/A')}")
        return True
    else:
        error = result.get("error", "未知错误")
        print(f"❌ 降级模式下也失败: {error}")
        # 如果是 API 配置问题，也算测试通过
        if "token" in error.lower() or "不可用" in error:
            print("ℹ️  降级逻辑正常，但 StockService API 未配置")
            return True
        return False


async def main():
    """主函数"""
    print("\n开始 MCP 最小化测试...")

    # 测试 1: 尝试真实连接
    real_success = await test_basic_connection()

    if not real_success:
        print("\n⚠️  MCP 连接失败，开始测试降级模式...")
        # 测试 2: Mock 模式
        mock_success = await test_with_mock()

        if mock_success:
            print("\n✅ 降级机制正常工作")
        else:
            print("\n❌ 降级机制也有问题")
    else:
        print("\n✅ MCP 连接和功能正常")

    print("\n" + "="*80)
    print("测试完成")
    print("="*80)


if __name__ == "__main__":
    asyncio.run(main())
