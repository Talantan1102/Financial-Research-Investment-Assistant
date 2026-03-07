#!/usr/bin/env python3
"""
验证 Tushare 自定义 API URL 配置修改

不依赖 tushare/mcp 包，仅检查代码结构是否正确
"""

import os
import sys

def check_file_exists(filepath, description):
    """检查文件是否存在"""
    print(f"\n检查 {description}...")
    if os.path.exists(filepath):
        print(f"  ✅ 文件存在: {filepath}")
        return True
    else:
        print(f"  ❌ 文件不存在: {filepath}")
        return False

def check_code_contains(filepath, patterns, description):
    """检查代码是否包含特定模式"""
    print(f"\n检查 {description}...")
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        missing = []
        for pattern in patterns:
            if pattern not in content:
                missing.append(pattern)
        
        if not missing:
            print(f"  ✅ 所有模式都存在")
            return True
        else:
            print(f"  ❌ 缺少模式:")
            for m in missing:
                print(f"    - {m}")
            return False
    except Exception as e:
        print(f"  ❌ 读取文件失败: {e}")
        return False

def main():
    print("=" * 70)
    print("验证 Tushare 自定义 API URL 配置修改")
    print("=" * 70)
    
    # 使用当前工作目录作为基准
    work_dir = os.getcwd()
    print(f"工作目录: {work_dir}")
    
    results = []
    
    # 检查文件存在
    tushare_client_path = os.path.join(work_dir, 'backend/app/data/tushare_client.py')
    config_path = os.path.join(work_dir, 'backend/app/mcp_server/config.py')
    
    results.append(check_file_exists(tushare_client_path, "tushare_client.py"))
    results.append(check_file_exists(config_path, "config.py"))
    
    # 检查 tushare_client.py 修改
    patterns_tushare = [
        "TUSHARE_API_URL",
        "self.api_url",
        "_DataApi__http_url",
    ]
    results.append(check_code_contains(tushare_client_path, patterns_tushare, "tushare_client.py 关键代码"))
    
    # 检查 config.py 修改
    patterns_config = [
        "tushare_api_url",
        "TUSHARE_API_URL",
        "https://api.tushare.pro",
    ]
    results.append(check_code_contains(config_path, patterns_config, "config.py 关键代码"))
    
    # 总结
    print("\n" + "=" * 70)
    print("验证结果")
    print("=" * 70)
    passed = sum(results)
    total = len(results)
    print(f"检查项: {passed}/{total} 通过")
    
    if passed == total:
        print("✅ 所有验证通过!")
        print("\n修改内容总结:")
        print("1. tushare_client.py: 添加 api_url 参数，支持自定义 URL")
        print("2. config.py: 添加 tushare_api_url 配置项")
        print("\n使用方式:")
        print('export TUSHARE_API_TOKEN="your_token"')
        print('export TUSHARE_API_URL="http://lianghua.nanyangqiankun.top"')
        return 0
    else:
        print("❌ 部分验证失败")
        return 1

if __name__ == "__main__":
    sys.exit(main())
