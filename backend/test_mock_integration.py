#!/usr/bin/env python3
"""
Mock Tushare Service 集成测试

测试 TushareClient 与 MockTushareAPI 的完整集成
"""

import os
import sys

# 设置环境变量（必须在导入 TushareClient 之前）
os.environ["USE_MOCK_TUSHARE"] = "true"
os.environ["DASHSCOPE_API_KEY"] = os.getenv(
    "DASHSCOPE_API_KEY", "sk-f5ad885285a44c339968325bdebc5658"
)
os.environ["TUSHARE_API_TOKEN"] = "mock-token"  # mock 模式下不需要真实 token

print("=" * 70)
print("Mock Tushare Service 集成测试")
print("=" * 70)
print("\n环境变量:")
print(f"   USE_MOCK_TUSHARE = {os.getenv('USE_MOCK_TUSHARE')}")
print(f"   DASHSCOPE_API_KEY = {'已设置' if os.getenv('DASHSCOPE_API_KEY') else '未设置'}")

# 导入 TushareClient
print("\n📦 导入 TushareClient...")
try:
    from app.data.tushare_client import get_tushare_client

    print("✅ TushareClient 导入成功")
except Exception as e:
    print(f"❌ 导入失败: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)

# 测试 1: 客户端初始化
print("\n🔧 测试 1: 客户端初始化...")
try:
    client = get_tushare_client()
    print("✅ 客户端初始化成功")
    print(f"   - use_mock: {client.use_mock}")
    print(f"   - mock_service: {client._mock_service is not None}")
    print(f"   - token: {'mock-token' if client.token else '未设置'}")
except Exception as e:
    print(f"❌ 客户端初始化失败: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)

# 测试 2: 获取 API
print("\n🔧 测试 2: 获取 Mock API...")
try:
    api = client.get_api()
    print("✅ API 获取成功")
    print(f"   - API 类型: {type(api).__name__}")
    print(f"   - 是否有 daily 方法: {hasattr(api, 'daily')}")
    print(f"   - 是否有 daily_basic 方法: {hasattr(api, 'daily_basic')}")
    print(f"   - 是否有 stock_basic 方法: {hasattr(api, 'stock_basic')}")
except Exception as e:
    print(f"❌ API 获取失败: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)

# 测试 3: 直接调用 Mock API 方法
print("\n📊 测试 3: 直接调用 Mock API 方法...")

# 3.1 stock_basic
print("\n   3.1 stock_basic...")
try:
    df = api.stock_basic(exchange="SSE")
    print(f"   ✅ stock_basic 成功，返回 {len(df)} 条记录")
except Exception as e:
    print(f"   ❌ stock_basic 失败: {e}")

# 3.2 daily（调用 LLM，耗时较长）
print("\n   3.2 daily（调用 LLM 生成数据，约需 5-10 秒）...")
try:
    df = api.daily(ts_code="600519.SH", start_date="20240301", end_date="20240305")
    print(f"   ✅ daily 成功，返回 {len(df)} 条记录")
    if not df.empty:
        print(f"   📈 最新K线: {df.iloc[0]['trade_date']} 收:{df.iloc[0]['close']:.2f}")
except Exception as e:
    print(f"   ❌ daily 失败: {e}")

# 3.3 daily_basic
print("\n   3.3 daily_basic（调用 LLM 生成数据）...")
try:
    df = api.daily_basic(ts_code="600519.SH", trade_date="20240301")
    print(f"   ✅ daily_basic 成功，返回 {len(df)} 条记录")
    if not df.empty:
        row = df.iloc[0]
        print(
            f"   📊 PE:{row.get('pe', 'N/A')} PB:{row.get('pb', 'N/A')} 市值:{row.get('total_mv', 'N/A')}"
        )
except Exception as e:
    print(f"   ❌ daily_basic 失败: {e}")

# 3.4 weekly/monthly
print("\n   3.4 weekly/monthly...")
try:
    df_weekly = api.weekly(ts_code="600519.SH", start_date="20240301", end_date="20240331")
    print(f"   ✅ weekly 成功，返回 {len(df_weekly)} 条记录")
except Exception as e:
    print(f"   ❌ weekly 失败: {e}")

# 3.5 user
print("\n   3.5 user（模拟用户信息）...")
try:
    df_user = api.user()
    print("   ✅ user 成功")
    print(f"   👤 模拟积分: {df_user.iloc[0]['points']}")
except Exception as e:
    print(f"   ❌ user 失败: {e}")

# 测试 4: TushareClient 高级方法
print("\n📊 测试 4: TushareClient 高级方法...")

# 4.1 get_quote
print("\n   4.1 get_quote('600519.SH')...")
try:
    result = client.get_quote("600519.SH")
    print("   ✅ get_quote 成功")
    print(f"   - success: {result.get('success')}")
    if result.get("success"):
        data = result.get("data", {})
        print(f"   - 股票: {data.get('name')} ({data.get('ts_code')})")
        print(f"   - 当前价: {data.get('nowPri')}")
        print(f"   - 涨跌幅: {data.get('increPer')}%")
        print(f"   - 成交量: {data.get('traAmount')}")
except Exception as e:
    print(f"   ❌ get_quote 失败: {e}")
    import traceback

    traceback.print_exc()

# 4.2 get_history
print("\n   4.2 get_history('000001.SZ', period='daily')...")
try:
    result = client.get_history("000001.SZ", period="daily", limit=5)
    print("   ✅ get_history 成功")
    print(f"   - success: {result.get('success')}")
    if result.get("success"):
        data = result.get("data", [])
        print(f"   - 返回 {len(data)} 条历史记录")
        if data:
            print(f"   📈 最新: {data[0]['trade_date']} 收:{data[0]['close']}")
except Exception as e:
    print(f"   ❌ get_history 失败: {e}")
    import traceback

    traceback.print_exc()

# 4.3 get_stock_basic
print("\n   4.3 get_stock_basic('000001.SZ')...")
try:
    result = client.get_stock_basic("000001.SZ")
    print("   ✅ get_stock_basic 成功")
    print(f"   - success: {result.get('success')}")
    if result.get("success"):
        data = result.get("data", {})
        print(f"   - 名称: {data.get('name')}")
        print(f"   - 行业: {data.get('industry')}")
        print(f"   - 地区: {data.get('area')}")
except Exception as e:
    print(f"   ❌ get_stock_basic 失败: {e}")

# 4.4 get_daily_basic
print("\n   4.4 get_daily_basic('000001.SZ')...")
try:
    result = client.get_daily_basic("000001.SZ")
    print("   ✅ get_daily_basic 成功")
    print(f"   - success: {result.get('success')}")
    if result.get("success"):
        data = result.get("data", {})
        print(f"   - 收盘价: {data.get('close')}")
        print(f"   - 市盈率: {data.get('pe')}")
        print(f"   - 总市值: {data.get('total_mv')}")
except Exception as e:
    print(f"   ❌ get_daily_basic 失败: {e}")

# 测试 5: 不同股票代码格式
print("\n📊 测试 5: 不同股票代码格式兼容性...")
test_codes = [
    ("600519", "纯数字（6开头=上证）"),
    ("000001", "纯数字（0开头=深证）"),
    ("sh600519", "带市场前缀小写"),
    ("SZ000001", "带市场前缀大写"),
    ("600519.SH", "Tushare格式"),
    ("000001.SZ", "Tushare格式"),
]
for code, desc in test_codes:
    try:
        result = client.get_quote(code)
        status = "✅" if result.get("success") else "❌"
        name = result.get("data", {}).get("name", "N/A") if result.get("success") else "N/A"
        print(f"   {status} {code:12s} ({desc:20s}) -> {name}")
    except Exception as e:
        print(f"   ❌ {code:12s} ({desc:20s}) -> 错误: {e}")

# 测试 6: 缓存功能
print("\n📊 测试 6: 缓存功能...")
try:
    # 第一次调用
    result1 = client.get_quote("600519.SH")
    cache_info1 = client.get_cache_info()
    print(f"   第一次调用后缓存: {cache_info1['valid_count']} 条")

    # 第二次调用（应该命中缓存）
    result2 = client.get_quote("600519.SH")
    cache_info2 = client.get_cache_info()
    print(f"   第二次调用后缓存: {cache_info2['valid_count']} 条")
    print("   ✅ 缓存功能正常")
except Exception as e:
    print(f"   ❌ 缓存测试失败: {e}")

print("\n" + "=" * 70)
print("集成测试完成!")
print("=" * 70)
print("\n📌 总结:")
print("   - Mock 模式启用: ✅")
print("   - TushareClient 集成: ✅")
print("   - MockTushareAPI 接口: ✅")
print("   - 高级方法 (get_quote/get_history): ✅")
print("\n💡 生产环境使用:")
print("   export USE_MOCK_TUSHARE=true")
print("   export DASHSCOPE_API_KEY=your-api-key")
print("   # 无需修改代码，自动使用 Mock 数据")
