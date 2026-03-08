#!/usr/bin/env python3
"""
测试 Brave Search API - 多端点尝试
"""
import asyncio
import aiohttp
import json


async def test_endpoint(base_url: str, endpoint: str, api_key: str):
    """测试特定端点"""

    full_url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"

    print(f"\n{'=' * 60}")
    print(f"测试端点: {full_url}")
    print('=' * 60)

    async with aiohttp.ClientSession() as session:
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        payload = {
            'q': '小米汽车',
            'count': 3
        }

        try:
            async with session.post(
                full_url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                status = response.status
                text = await response.text()

                print(f"状态码: {status}")

                if status == 200:
                    try:
                        data = json.loads(text)
                        print(f"✅ 成功!")
                        print(f"返回键: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")

                        if 'web' in data and 'results' in data['web']:
                            results = data['web']['results']
                            print(f"搜索结果数: {len(results)}")
                            if results:
                                print(f"\n第一条结果:")
                                print(f"  标题: {results[0].get('title', 'N/A')}")
                                print(f"  URL: {results[0].get('url', 'N/A')}")

                        return True
                    except json.JSONDecodeError:
                        print(f"✅ 返回成功，但不是 JSON: {text[:200]}")
                        return True
                else:
                    print(f"❌ 失败")
                    print(f"响应: {text[:300]}")
                    return False

        except Exception as e:
            print(f"❌ 异常: {type(e).__name__}: {str(e)}")
            return False


async def test_all_endpoints():
    """测试所有可能的端点"""

    api_key = "BSAnCeCzDV_X3FUmxGpm3MPhiqe7klm"
    base_url = "http://api.wlai.vip"

    print("=" * 60)
    print("🔍 Brave Search API 多端点测试")
    print("=" * 60)
    print(f"\nAPI Key: {api_key[:20]}...{api_key[-8:]}")
    print(f"基础 URL: {base_url}")

    # 尝试不同的端点
    endpoints = [
        'v1/search',
        'search',
        'brave/search',
        'api/search',
        'v1/brave/search',
        '',  # 直接使用基础 URL
    ]

    results = {}

    for endpoint in endpoints:
        success = await test_endpoint(base_url, endpoint, api_key)
        results[endpoint or 'base'] = success
        await asyncio.sleep(1)  # 避免请求过快

    # 总结
    print("\n\n" + "=" * 60)
    print("📊 测试结果汇总")
    print("=" * 60)

    successful_endpoints = [ep for ep, success in results.items() if success]

    if successful_endpoints:
        print(f"\n✅ 可用的端点:")
        for ep in successful_endpoints:
            full_url = f"{base_url}/{ep}" if ep != 'base' else base_url
            print(f"  - {full_url}")
    else:
        print("\n❌ 所有端点均不可用")
        print("\n可能的原因:")
        print("  1. API Key 不正确")
        print("  2. 代理服务器地址错误")
        print("  3. 需要不同的认证方式")
        print("  4. 服务暂时不可用")


async def test_get_request():
    """尝试 GET 请求"""

    print("\n\n" + "=" * 60)
    print("🧪 尝试 GET 请求")
    print("=" * 60)

    api_key = "BSAnCeCzDV_X3FUmxGpm3MPhiqe7klm"

    test_urls = [
        f"http://api.wlai.vip/v1/search?q=test&count=3",
        f"http://api.wlai.vip/search?q=test&count=3",
    ]

    async with aiohttp.ClientSession() as session:
        for url in test_urls:
            print(f"\n测试 URL: {url}")

            headers = {
                'Authorization': f'Bearer {api_key}',
            }

            try:
                async with session.get(
                    url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as response:
                    status = response.status
                    text = await response.text()

                    print(f"状态码: {status}")
                    if status == 200:
                        print(f"✅ 成功: {text[:200]}")
                    else:
                        print(f"❌ 失败: {text[:200]}")
            except Exception as e:
                print(f"❌ 异常: {str(e)}")


if __name__ == "__main__":
    print("\n🚀 开始 Brave Search API 端点探测\n")

    # 测试所有端点
    asyncio.run(test_all_endpoints())

    # 测试 GET 请求
    asyncio.run(test_get_request())

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
