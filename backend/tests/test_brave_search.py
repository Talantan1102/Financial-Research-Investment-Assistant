#!/usr/bin/env python3
"""
测试 Brave Search API 连接性
使用专用代理: http://api.wlai.vip/v1/search
"""
import asyncio
import os
import aiohttp
import json


async def test_brave_search_proxy():
    """测试 Brave Search API - 使用代理"""

    print("=" * 60)
    print("🔍 Brave Search API 测试 (代理)")
    print("=" * 60)

    # 专用配置
    api_key = "BSAnCeCzDV_X3FUmxGpm3MPhiqe7klm"
    proxy_url = "http://api.wlai.vip"  # 基础 URL，可能需要调整路径

    print(f"\n✓ API Key: {api_key[:20]}...{api_key[-8:]}")
    print(f"✓ 代理地址: {proxy_url}")

    try:
        print("\n" + "=" * 60)
        print("📡 发送测试搜索请求")
        print("=" * 60)

        query = "小米汽车"
        print(f"\n🔎 搜索查询: {query}")

        # 使用 aiohttp 直接调用代理 API
        async with aiohttp.ClientSession() as session:
            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            }

            payload = {
                'q': query,
                'country': 'CN',
                'search_lang': 'zh-hans',
                'count': 5
            }

            print(f"\n📤 请求参数: {json.dumps(payload, ensure_ascii=False)}")

            async with session.post(
                proxy_url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                status = response.status
                print(f"\n📥 响应状态码: {status}")

                if status == 200:
                    data = await response.json()

                    print("\n" + "=" * 60)
                    print("✅ 搜索成功！")
                    print("=" * 60)

                    # 解析结果
                    if 'web' in data and 'results' in data['web']:
                        results = data['web']['results']
                        print(f"\n📊 返回 {len(results)} 条结果:\n")

                        for i, item in enumerate(results[:5], 1):
                            print(f"\n{i}. {item.get('title', 'N/A')}")
                            print(f"   URL: {item.get('url', 'N/A')}")
                            desc = item.get('description', 'N/A')
                            print(f"   摘要: {desc[:100]}...")

                        return True
                    else:
                        print("\n⚠️  未返回搜索结果")
                        print(f"响应数据: {json.dumps(data, ensure_ascii=False, indent=2)[:500]}...")
                        return False
                else:
                    error_text = await response.text()
                    print(f"\n❌ HTTP 错误 {status}")
                    print(f"错误响应: {error_text[:500]}...")
                    return False

    except Exception as e:
        print("\n" + "=" * 60)
        print("❌ 搜索失败")
        print("=" * 60)
        print(f"\n错误类型: {type(e).__name__}")
        print(f"错误信息: {str(e)}")

        import traceback
        print("\n完整错误堆栈:")
        print(traceback.format_exc())

        return False


async def test_simple_query():
    """测试简单查询"""

    print("\n\n" + "=" * 60)
    print("🧪 简单查询测试")
    print("=" * 60)

    api_key = "BSAnCeCzDV_X3FUmxGpm3MPhiqe7klm"
    proxy_url = "http://api.wlai.vip"  # 基础 URL

    async with aiohttp.ClientSession() as session:
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        payload = {
            'q': 'test',
            'count': 3
        }

        try:
            async with session.post(
                proxy_url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                status = response.status
                print(f"状态码: {status}")

                if status == 200:
                    data = await response.json()
                    print(f"✅ 连接成功")
                    print(f"返回数据类型: {type(data)}")
                    print(f"返回数据键: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")
                else:
                    text = await response.text()
                    print(f"❌ 失败: {text[:200]}")
        except Exception as e:
            print(f"❌ 异常: {str(e)}")


if __name__ == "__main__":
    print("\n🚀 开始测试 Brave Search API (代理)\n")

    # 运行主测试
    success = asyncio.run(test_brave_search_proxy())

    # 运行简单测试
    asyncio.run(test_simple_query())

    print("\n" + "=" * 60)
    if success:
        print("✅ 测试完成 - Brave Search API 可用")
    else:
        print("❌ 测试完成 - Brave Search API 不可用")
    print("=" * 60)
