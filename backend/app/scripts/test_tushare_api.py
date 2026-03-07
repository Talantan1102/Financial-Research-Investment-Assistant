#!/usr/bin/env python3
"""
快速验证 Tushare API Token 是否有效
"""
import os
import sys
import asyncio

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

# 设置环境变量
os.environ['TUSHARE_API_TOKEN'] = '5a05084f5dbb829c251ffa1a15061529ba56a96c9988b5100057bed8'

from app.mcp_server.skills import MarketDataSkill

async def test_tushare_api():
    """测试 Tushare API 调用"""
    print("\n" + "="*60)
    print("测试 Tushare API Token 有效性")
    print("="*60)
    
    try:
        # 创建 MarketData Skill
        skill = MarketDataSkill()
        print("✅ MarketDataSkill 初始化成功")
        
        # 测试获取茅台股票数据
        print("\n📈 测试获取 600519 茅台股票数据...")
        result = await skill.execute_tool("get_quote", {"symbol": "600519"})
        
        if result.success:
            data = result.data
            print(f"✅ 获取成功!")
            print(f"   股票名称: {data.get('name')}")
            print(f"   当前价格: {data.get('nowPri')}")
            print(f"   涨跌幅: {data.get('increPer')}%")
            print(f"   涨跌额: {data.get('increase')}")
        else:
            print(f"❌ 获取失败: {result.error}")
            
        # 测试获取平安银行数据
        print("\n📈 测试获取 000001 平安银行股票数据...")
        result2 = await skill.execute_tool("get_quote", {"symbol": "000001"})
        
        if result2.success:
            data = result2.data
            print(f"✅ 获取成功!")
            print(f"   股票名称: {data.get('name')}")
            print(f"   当前价格: {data.get('nowPri')}")
            print(f"   涨跌幅: {data.get('increPer')}%")
        else:
            print(f"❌ 获取失败: {result2.error}")
            
        # 测试搜索功能
        print("\n🔍 测试股票搜索功能...")
        result3 = await skill.execute_tool("search_stock", {"keyword": "茅台"})
        
        if result3.success:
            data = result3.data
            results = data.get('results', []) if isinstance(data, dict) else []
            print(f"✅ 搜索成功! 找到 {len(results)} 个结果")
            for i, stock in enumerate(results[:3], 1):
                print(f"   {i}. {stock.get('name')} ({stock.get('gid')})")
        else:
            print(f"❌ 搜索失败: {result3.error}")
            
        print("\n" + "="*60)
        print("Tushare API 测试完成")
        print("="*60)
        
    except Exception as e:
        print(f"❌ 测试失败: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_tushare_api())
