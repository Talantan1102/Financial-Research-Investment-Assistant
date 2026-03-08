#!/usr/bin/env python3
"""
测试博查 API 搜索功能
"""
import asyncio
import aiohttp
import json
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


async def test_bocha_search():
    """测试博查搜索 API"""

    print("=" * 60)
    print("🔍 博查 API 测试")
    print("=" * 60)

    # 获取 API Key
    api_key = os.getenv('BOCHA_API_KEY') or os.getenv('SEARCH_API_KEY')
    if not api_key:
        print("\n❌ 未找到 BOCHA_API_KEY 或 SEARCH_API_KEY 环境变量")
        return False

    print(f"\n✓ API Key: {api_key[:20]}...{api_key[-8:]}")

    # API 配置
    url = "https://api.bochaai.com/v1/web-search"
    headers = {
        'Authorization': api_key,
        'Content-Type': 'application/json'
    }

    # 测试查询
    queries = [
        "小米汽车",
        "比亚迪最新销量",
        "特斯拉中国"
    ]

    for query in queries:
        print("\n" + "=" * 60)
        print(f"🔎 搜索查询: {query}")
        print("=" * 60)

        payload = {
            "query": query,
            "summary": True,
            "count": 5,
            "page": 1
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    status = response.status
                    print(f"\n📥 响应状态码: {status}")

                    if status == 200:
                        data = await response.json()

                        # 解析结果
                        webpages_data = data.get('data', {}).get('webPages', {})
                        value_list = webpages_data.get('value', [])

                        if value_list:
                            print(f"\n✅ 搜索成功！返回 {len(value_list)} 条结果:\n")

                            for i, item in enumerate(value_list[:3], 1):
                                print(f"{i}. {item.get('name', 'N/A')}")
                                print(f"   URL: {item.get('url', 'N/A')}")
                                print(f"   来源: {item.get('siteName', 'N/A')}")
                                snippet = item.get('snippet', item.get('summary', ''))
                                print(f"   摘要: {snippet[:100]}...")
                                print()
                        else:
                            print("\n⚠️  未返回搜索结果")
                            print(f"响应数据: {json.dumps(data, ensure_ascii=False, indent=2)[:500]}...")

                    else:
                        error_text = await response.text()
                        print(f"\n❌ HTTP 错误 {status}")
                        print(f"错误响应: {error_text[:500]}...")
                        return False

        except asyncio.TimeoutError:
            print(f"\n❌ 请求超时")
            return False
        except Exception as e:
            print(f"\n❌ 异常: {type(e).__name__}: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

        await asyncio.sleep(1)  # 避免请求过快

    return True


async def test_simple_query():
    """测试单个简单查询"""

    print("\n\n" + "=" * 60)
    print("🧪 简单查询测试")
    print("=" * 60)

    api_key = os.getenv('BOCHA_API_KEY') or os.getenv('SEARCH_API_KEY')
    if not api_key:
        print("\n❌ 未找到 API Key")
        return False

    url = "https://api.bochaai.com/v1/web-search"
    headers = {
        'Authorization': api_key,
        'Content-Type': 'application/json'
    }

    payload = {
        "query": "test",
        "count": 3
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                status = response.status
                print(f"\n状态码: {status}")

                if status == 200:
                    data = await response.json()
                    print(f"✅ 连接成功")
                    print(f"返回数据键: {list(data.keys())}")
                    return True
                else:
                    text = await response.text()
                    print(f"❌ 失败: {text[:200]}")
                    return False
    except Exception as e:
        print(f"❌ 异常: {str(e)}")
        return False


if __name__ == "__main__":
    print("\n🚀 开始测试博查 API\n")

    # 运行简单测试
    simple_success = asyncio.run(test_simple_query())

    if simple_success:
        # 运行完整测试
        success = asyncio.run(test_bocha_search())

        print("\n" + "=" * 60)
        if success:
            print("✅ 测试完成 - 博查 API 可用")
        else:
            print("⚠️  测试完成 - 部分功能可能有问题")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("❌ 测试失败 - 博查 API 不可用")
        print("=" * 60)
