#!/usr/bin/env python3
"""
MCP Server 测试脚本

测试 MCP Server 的启动和工具调用
"""

import asyncio
import json
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.mcp_server.server import FinancialMCPServer
from app.mcp_server.config import get_config


async def test_server():
    """测试Server"""
    print("=" * 60)
    print("Financial MCP Server 测试")
    print("=" * 60)
    
    # 加载配置
    config = get_config()
    print("\n📋 配置信息:")
    print(json.dumps(config.to_dict(), indent=2, ensure_ascii=False))
    
    # 创建Server
    print("\n🔧 创建MCP Server...")
    server = FinancialMCPServer(config)
    
    # 初始化
    print("\n🚀 初始化Server...")
    success = await server.initialize()
    if not success:
        print("❌ Server初始化失败")
        return False
    
    print("✅ Server初始化成功")
    
    # 获取Server信息
    print("\n📊 Server信息:")
    info = server.get_server_info()
    print(json.dumps(info, indent=2, ensure_ascii=False))
    
    # 获取工具列表
    print("\n🔍 可用工具列表:")
    try:
        tools = await server.server.request_context.session.list_tools()
        if hasattr(tools, 'tools'):
            tools = tools.tools
        for tool in tools:
            print(f"  - {tool.name}: {tool.description[:50]}...")
    except Exception as e:
        print(f"  注: 工具列表获取需要完整MCP连接: {e}")
    
    # 直接测试Skill
    print("\n🧪 测试Skill执行:")
    from app.mcp_server.skills import MarketDataSkill
    
    market_skill = server.skills.get("market_data")
    if market_skill:
        print(f"  - MarketDataSkill 工具: {market_skill.get_tool_names()}")
        
        # 测试get_quote工具
        if market_skill.has_tool("get_quote"):
            print("\n  📈 测试 get_quote 工具...")
            try:
                result = await market_skill.execute_tool("get_quote", {"symbol": "600519", "include_details": False})
                if result.success:
                    data = result.data.get("data", {})
                    print(f"    ✅ 成功获取股票数据:")
                    print(f"       名称: {data.get('name')}")
                    print(f"       代码: {data.get('code')}")
                    print(f"       当前价: {data.get('nowPri')}")
                else:
                    print(f"    ⚠️ 获取失败: {result.error}")
                    print("    注: 需要配置有效的TUSHARE_API_TOKEN")
            except Exception as e:
                print(f"    ❌ 执行出错: {e}")
    
    # 清理
    print("\n🧹 清理资源...")
    await server.cleanup()
    print("✅ 清理完成")
    
    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)
    
    return True


async def test_tushare_only():
    """仅测试Tushare客户端"""
    print("=" * 60)
    print("Tushare Client 独立测试")
    print("=" * 60)
    
    from app.data.tushare_client import get_tushare_client
    
    print("\n🔧 创建Tushare客户端...")
    client = get_tushare_client()
    
    print("\n📊 缓存信息:")
    print(json.dumps(client.get_cache_info(), indent=2))
    
    print("\n🧪 测试获取股票行情 (600519 - 贵州茅台)...")
    result = client.get_quote("600519")
    
    if result["success"]:
        data = result["data"]
        print("✅ 获取成功!")
        print(f"\n  股票信息:")
        print(f"    名称: {data.get('name')}")
        print(f"    代码: {data.get('ts_code')}")
        print(f"    当前价: {data.get('nowPri')}")
        print(f"    涨跌额: {data.get('increase')}")
        print(f"    涨跌幅: {data.get('increPer')}%")
        print(f"    开盘价: {data.get('todayStartPri')}")
        print(f"    最高价: {data.get('todayMax')}")
        print(f"    最低价: {data.get('todayMin')}")
        print(f"    成交量: {data.get('traAmount')} 手")
        return True
    else:
        print(f"⚠️ 获取失败: {result.get('error')}")
        print("\n  可能原因:")
        print("    1. TUSHARE_API_TOKEN 环境变量未设置")
        print("    2. Tushare API Token 无效或已过期")
        print("    3. 网络连接问题")
        print("\n  解决方法:")
        print("    export TUSHARE_API_TOKEN=your_token_here")
        return False


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="MCP Server 测试")
    parser.add_argument(
        "--tushare-only",
        action="store_true",
        help="仅测试Tushare客户端"
    )
    
    args = parser.parse_args()
    
    if args.tushare_only:
        asyncio.run(test_tushare_only())
    else:
        asyncio.run(test_server())
