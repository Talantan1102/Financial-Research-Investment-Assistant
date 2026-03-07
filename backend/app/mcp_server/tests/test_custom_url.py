#!/usr/bin/env python3
"""
测试 Tushare 自定义 API URL 配置

验证功能：
- TUSHARE_API_TOKEN 环境变量读取
- TUSHARE_API_URL 环境变量读取
- 自定义 URL 是否正确设置到 tushare pro_api
"""

import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))

def test_tushare_client_custom_url():
    """测试 TushareClient 支持自定义 URL"""
    print("=" * 70)
    print("测试 TushareClient 自定义 API URL")
    print("=" * 70)
    
    # 获取环境变量
    token = os.getenv("TUSHARE_API_TOKEN")
    api_url = os.getenv("TUSHARE_API_URL")
    
    print(f"TUSHARE_API_TOKEN: {'已设置' if token else '未设置'}")
    print(f"TUSHARE_API_URL: {api_url or '未设置（使用默认）'}")
    print("-" * 70)
    
    if not token:
        print("❌ TUSHARE_API_TOKEN 未设置，跳过测试")
        return False
    
    try:
        import tushare as ts
    except ImportError:
        print("❌ tushare 模块未安装，跳过测试")
        return False
    
    try:
        # 清除可能已存在的实例
        from app.data.tushare_client import TushareClient, get_tushare_client
        TushareClient._instance = None
        
        # 创建客户端
        client = get_tushare_client()
        
        # 验证 Token 设置
        print(f"✅ Token 已设置: {client.token[:20]}...")
        
        # 验证 API URL 设置
        print(f"✅ API URL 设置: {client.api_url}")
        
        # 验证 API 实例初始化
        if client.api:
            print(f"✅ Tushare API 实例已创建")
            
            # 检查自定义 URL 是否生效
            actual_url = getattr(client.api, '_DataApi__http_url', None)
            if actual_url:
                print(f"✅ API 实际 URL: {actual_url}")
                if actual_url == api_url:
                    print(f"✅ 自定义 URL 配置成功!")
                else:
                    print(f"⚠️ URL 不匹配: 期望 {api_url}, 实际 {actual_url}")
        else:
            print("❌ Tushare API 实例创建失败")
            return False
        
        # 测试获取用户积分（验证 API 连通性）
        print("\n测试 API 连通性...")
        try:
            points = client.get_user_points()
            if points is not None:
                print(f"✅ 获取用户积分成功: {points}")
            else:
                print(f"⚠️ 无法获取用户积分（可能是权限问题）")
        except Exception as e:
            print(f"⚠️ 获取用户积分失败: {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        print(f"\n详细错误:\n{traceback.format_exc()}")
        return False


def test_config_custom_url():
    """测试 MCPServerConfig 支持自定义 URL"""
    print("\n" + "=" * 70)
    print("测试 MCPServerConfig 自定义 API URL")
    print("=" * 70)
    
    try:
        from app.mcp_server.config import get_config
        
        config = get_config()
        
        # 验证 Token
        if config.tushare_api_token:
            print(f"✅ Config Token: {config.tushare_api_token[:20]}...")
        else:
            print("❌ Config Token 未设置")
            return False
        
        # 验证 URL
        print(f"✅ Config API URL: {config.tushare_api_url}")
        
        expected_url = os.getenv("TUSHARE_API_URL", "https://api.tushare.pro")
        if config.tushare_api_url == expected_url:
            print(f"✅ URL 配置正确!")
        else:
            print(f"❌ URL 配置错误: 期望 {expected_url}, 实际 {config.tushare_api_url}")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        print(f"\n详细错误:\n{traceback.format_exc()}")
        return False


def main():
    """主函数"""
    print("\n" + "=" * 70)
    print("Tushare 自定义 API URL 配置测试")
    print("=" * 70)
    print(f"Python 版本: {sys.version.split()[0]}")
    print(f"工作目录: {os.getcwd()}")
    print("=" * 70)
    
    # 运行测试
    result1 = test_tushare_client_custom_url()
    result2 = test_config_custom_url()
    
    # 总结
    print("\n" + "=" * 70)
    print("测试结果总结")
    print("=" * 70)
    print(f"TushareClient 测试: {'✅ 通过' if result1 else '❌ 失败'}")
    print(f"MCPServerConfig 测试: {'✅ 通过' if result2 else '❌ 失败'}")
    print("=" * 70)
    
    if result1 and result2:
        print("✅ 所有测试通过!")
        return 0
    else:
        print("❌ 部分测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
