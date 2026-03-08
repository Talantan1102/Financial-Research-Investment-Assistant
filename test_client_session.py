#!/usr/bin/env python3
"""测试使用 ClientSession 连接 MCP Server（与实际 Client 代码相同的方式）"""
import asyncio
import os
import logging

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("TestClientSession")

async def test_client_session():
    # 设置环境变量
    os.environ["TUSHARE_API_TOKEN"] = "9e4123cf56aaa553b06556e64b05e9d8d004340d82897eb1704ccd91c088"
    os.environ["TUSHARE_API_URL"] = "http://lianghua.nanyangqiankun.top"

    server_script_path = "/Users/talantan/.openclaw/workspace-dev/external/financial-research-assistant/backend/app/mcp_server/server.py"
    python_executable = "python3"
    connect_timeout = 60.0

    print("=" * 70)
    print("测试 ClientSession 连接（与实际 MCPClient 相同的方式）")
    print("=" * 70)
    print()

    try:
        # 配置 STDIO 服务器参数
        env_vars = os.environ.copy()

        server_params = StdioServerParameters(
            command=python_executable,
            args=[server_script_path],
            env=env_vars
        )

        logger.info("正在启动 STDIO 客户端...")
        stdio_context = stdio_client(server_params)

        logger.info("正在连接 STDIO 流...")
        read_stream, write_stream = await stdio_context.__aenter__()

        logger.info("✓ STDIO 流连接成功")
        logger.info("正在创建 ClientSession...")

        # 创建会话
        session = ClientSession(read_stream, write_stream)

        logger.info(f"正在初始化会话（超时：{connect_timeout}s）...")
        logger.info("调用 session.initialize()...")

        # 这是关键步骤 - 与 MCPClient 完全相同
        await asyncio.wait_for(
            session.initialize(),
            timeout=connect_timeout
        )

        logger.info("✅ ClientSession 初始化成功！")

        # 尝试列出工具
        logger.info("尝试列出工具...")
        tools_response = await session.list_tools()
        logger.info(f"✓ 工具列表: {len(tools_response.tools)} 个工具")
        for tool in tools_response.tools:
            logger.info(f"  - {tool.name}: {tool.description}")

        # 清理
        await stdio_context.__aexit__(None, None, None)
        logger.info("✓ 连接已关闭")

        print("\n" + "=" * 70)
        print("✅ 测试成功！ClientSession 工作正常")
        print("=" * 70)

    except asyncio.TimeoutError:
        logger.error("❌ 初始化超时！")
        logger.error("这表明 session.initialize() 没有收到响应或挂起")

    except Exception as e:
        logger.error(f"❌ 测试失败: {type(e).__name__}: {e}")
        import traceback
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    asyncio.run(test_client_session())
