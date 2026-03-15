#!/usr/bin/env python3
"""金融研投助手集成测试"""
import sys
import os
import asyncio

os.environ['TUSHARE_API_TOKEN'] = '9e4123cf56aaa553b06556e64b05e9d8d004340d82897eb1704ccd91c088'
os.environ['TUSHARE_API_URL'] = 'http://lianghua.nanyangqiankun.top'

sys.path.insert(0, '/Users/talantan/.openclaw/workspace-dev/external/AgentFlow')
sys.path.insert(0, '/Users/talantan/.openclaw/workspace-dev/external/financial-research-assistant/backend')


class TestFinanceIntegration:
    """金融研投助手集成测试类"""
    
    def __init__(self):
        self.backend = None
        
    async def setup(self):
        """初始化测试环境"""
        from sandbox.server.backends.resources.unified_finance import UnifiedFinanceBackend
        self.backend = UnifiedFinanceBackend()
        await self.backend.warmup()
        print(f"✅ Backend 初始化成功")
        
    async def test_market_data_get_quote(self):
        """测试获取股票行情"""
        result = await self.backend.action_execute_skill_tool(
            skill_name='market_data',
            tool_name='get_quote',
            arguments={'symbol': '600519'}
        )
        assert result.get('code') == 0
        data = result.get('data', {})
        print(f"✅ get_quote: {data.get('name')} ¥{data.get('nowPri')}")
        return True
        
    async def run_all(self):
        """运行所有测试"""
        print("=" * 60)
        print("🧪 金融研投助手集成测试")
        print("=" * 60)
        await self.setup()
        await self.test_market_data_get_quote()
        print("=" * 60)
        print("✅ 所有测试通过!")
        print("=" * 60)


if __name__ == "__main__":
    test = TestFinanceIntegration()
    asyncio.run(test.run_all())
