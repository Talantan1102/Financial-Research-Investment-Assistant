#!/usr/bin/env python3
"""
Mock Tushare Service 测试脚本

此脚本独立运行，无需安装 tushare 库
"""

import os
import sys
import asyncio
from datetime import datetime

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 检查环境变量
if not os.getenv('DASHSCOPE_API_KEY'):
    print("⚠️  警告: DASHSCOPE_API_KEY 环境变量未设置")
    print("   测试 stock_basic 可以正常工作，但 daily/daily_basic 需要有效的 API Key")
    print()

print("=" * 70)
print("Mock Tushare Service 测试")
print("=" * 70)

# 测试 1: 验证文件语法和导入
print("\n📦 测试 1: 验证模块导入...")
try:
    from app.service.mock_tushare_service import MockTushareService
    print("✅ MockTushareService 导入成功")
except Exception as e:
    print(f"❌ MockTushareService 导入失败: {e}")
    sys.exit(1)

# 测试 2: 实例化服务
print("\n🔧 测试 2: 实例化 MockTushareService...")
try:
    service = MockTushareService()
    print(f"✅ 实例化成功")
    print(f"   - 模型: {service.model}")
    print(f"   - 股票池数量: {len(service.MOCK_STOCKS)}")
except Exception as e:
    print(f"❌ 实例化失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 测试 3: 股票信息查询
print("\n📋 测试 3: 股票信息查询...")
try:
    stock = service._get_stock_info("600519.SH")
    print(f"✅ 股票查询成功")
    print(f"   - 代码: 600519.SH")
    print(f"   - 名称: {stock['name']}")
    print(f"   - 行业: {stock['industry']}")
    print(f"   - 地区: {stock['area']}")
    print(f"   - 市场: {stock['market']}")

    # 测试基准价格
    price = service._get_base_price("600519.SH")
    print(f"   - 基准价格: {price:.2f} 元")
except Exception as e:
    print(f"❌ 股票查询失败: {e}")
    import traceback
    traceback.print_exc()

# 测试 4: stock_basic（无需 LLM）
print("\n📊 测试 4: generate_stock_basic（静态数据）...")
try:
    df = asyncio.run(service.generate_stock_basic())
    print(f"✅ stock_basic 成功")
    print(f"   - 返回行数: {len(df)}")
    print(f"   - 返回列: {list(df.columns)}")
    print(f"\n   前5条数据预览:")
    preview_df = df.head(5)[['ts_code', 'symbol', 'name', 'industry', 'market']]
    for _, row in preview_df.iterrows():
        print(f"   - {row['ts_code']} | {row['name']:8s} | {row['industry']:6s} | {row['market']}")
except Exception as e:
    print(f"❌ stock_basic 失败: {e}")
    import traceback
    traceback.print_exc()

# 测试 5: stock_basic 带过滤
print("\n📊 测试 5: generate_stock_basic（按交易所过滤）...")
try:
    df_sse = asyncio.run(service.generate_stock_basic(exchange='SSE'))
    df_sze = asyncio.run(service.generate_stock_basic(exchange='SZE'))
    print(f"✅ 过滤查询成功")
    print(f"   - 上交所(SSE): {len(df_sse)} 只股票")
    print(f"   - 深交所(SZE): {len(df_sze)} 只股票")
except Exception as e:
    print(f"❌ 过滤查询失败: {e}")
    import traceback
    traceback.print_exc()

# 测试 6: daily（需要 LLM）
print("\n📈 测试 6: generate_daily_data（需要 LLM 调用）...")
print("   正在调用 LLM 生成K线数据，请稍候...")
try:
    df_daily = asyncio.run(service.generate_daily_data(
        ts_code='600519.SH',
        start_date='20240301',
        end_date='20240310'
    ))
    print(f"✅ daily 成功")
    print(f"   - 返回行数: {len(df_daily)}")
    print(f"   - 返回列: {list(df_daily.columns)}")
    if not df_daily.empty:
        print(f"\n   生成的K线数据预览:")
        preview = df_daily[['trade_date', 'open', 'high', 'low', 'close', 'pct_chg', 'vol']].head(5)
        for _, row in preview.iterrows():
            print(f"   - {row['trade_date']} | 开:{row['open']:7.2f} | 高:{row['high']:7.2f} | "
                  f"低:{row['low']:7.2f} | 收:{row['close']:7.2f} | 幅:{row['pct_chg']:5.2f}%")
except Exception as e:
    print(f"❌ daily 失败: {e}")
    print(f"   错误详情: {type(e).__name__}")
    if "api_key" in str(e).lower():
        print("   💡 提示: 需要设置有效的 DASHSCOPE_API_KEY 环境变量")

# 测试 7: daily_basic（需要 LLM）
print("\n📊 测试 7: generate_daily_basic（需要 LLM 调用）...")
print("   正在调用 LLM 生成指标数据，请稍候...")
try:
    df_basic = asyncio.run(service.generate_daily_basic(
        ts_code='600519.SH',
        trade_date='20240301'
    ))
    print(f"✅ daily_basic 成功")
    print(f"   - 返回行数: {len(df_basic)}")
    print(f"   - 返回列: {list(df_basic.columns)}")
    if not df_basic.empty:
        print(f"\n   生成的指标数据预览:")
        row = df_basic.iloc[0]
        print(f"   - 收盘价: {row.get('close', 'N/A')}")
        print(f"   - 市盈率: {row.get('pe', 'N/A')}")
        print(f"   - 市净率: {row.get('pb', 'N/A')}")
        print(f"   - 总市值: {row.get('total_mv', 'N/A')} 万元")
        print(f"   - 换手率: {row.get('turnover_rate', 'N/A')}%")
except Exception as e:
    print(f"❌ daily_basic 失败: {e}")
    if "api_key" in str(e).lower():
        print("   💡 提示: 需要设置有效的 DASHSCOPE_API_KEY 环境变量")

# 测试 8: 验证数据一致性
print("\n🔍 测试 8: 数据一致性检查...")
try:
    df_check = asyncio.run(service.generate_daily_data(
        ts_code='000001.SZ',
        start_date='20240301',
        end_date='20240305'
    ))
    if not df_check.empty:
        errors = []
        for _, row in df_check.iterrows():
            # 检查 OHLC 逻辑
            if row['high'] < max(row['open'], row['close'], row['low']):
                errors.append(f"{row['trade_date']}: high < max(open,close,low)")
            if row['low'] > min(row['open'], row['close'], row['high']):
                errors.append(f"{row['trade_date']}: low > min(open,close,high)")
            # 检查价格范围
            if row['close'] <= 0:
                errors.append(f"{row['trade_date']}: close <= 0")

        if errors:
            print(f"⚠️  发现 {len(errors)} 个数据问题:")
            for err in errors[:3]:
                print(f"   - {err}")
        else:
            print(f"✅ 数据一致性检查通过")
            print(f"   - 所有 {len(df_check)} 条K线数据的 OHLC 逻辑正确")
except Exception as e:
    print(f"⚠️  数据一致性检查跳过: {e}")

print("\n" + "=" * 70)
print("测试完成!")
print("=" * 70)
print("\n📌 总结:")
print("   - stock_basic: ✅ 无需 LLM，可直接使用")
print("   - daily/daily_basic: 需要设置 DASHSCOPE_API_KEY 环境变量")
print("\n💡 使用方式:")
print("   export USE_MOCK_TUSHARE=true")
print("   export DASHSCOPE_API_KEY=your-api-key")
print("   # 然后正常调用 TushareClient")
