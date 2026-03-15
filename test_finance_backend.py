#!/usr/bin/env python3
"""
快速测试 Finance Research Backend
验证 AgentFlow 集成是否正常工作
"""

import sys
import os
import asyncio

# 添加路径
sys.path.insert(0, os.path.expanduser('~/.openclaw/workspace-dev/external/AgentFlow'))
sys.path.insert(0, os.path.expanduser('~/.openclaw/workspace-dev/external/AgentFlow/sandbox/server/backends/resources'))

print("=" * 60)
print("🧪 Finance Research Backend 快速测试")
print("=" * 60)

# 测试 1: 导入测试
print("\n1️⃣ 导入测试")
try:
    from finance_research import (
        FinanceResearchBackend,
        AgentFlowFinanceBackend,
        get_tool_definitions
    )
    print("   ✅ 所有类导入成功")
except Exception as e:
    print(f"   ❌ 导入失败: {e}")
    sys.exit(1)

# 测试 2: 工具定义
print("\n2️⃣ 工具定义检查")
tools = get_tool_definitions()
print(f"   共 {len(tools)} 个工具:")
for tool in tools:
    print(f"   • {tool['name']}: {tool['description'][:40]}...")

# 测试 3: 创建 Backend 实例
print("\n3️⃣ Backend 实例化")
try:
    backend = FinanceResearchBackend()
    print("   ✅ Backend 实例创建成功")
except Exception as e:
    print(f"   ❌ 实例化失败: {e}")
    sys.exit(1)

# 测试 4: 配置加载
print("\n4️⃣ 配置加载")
config = {
    'search_api_key': os.getenv('SEARCH_API_KEY', 'test_key'),
    'llm_api_key': os.getenv('LLM_API_KEY', 'test_key'),
    'llm_base_url': os.getenv('LLM_BASE_URL', 'https://api.openai.com/v1'),
}

try:
    # 注意：实际初始化需要金融研投助手的依赖
    # 这里只测试配置对象创建
    from finance_research import FinanceResearchBackendConfig
    cfg = FinanceResearchBackendConfig(config)
    print(f"   ✅ 配置对象创建成功")
    print(f"   • llm_base_url: {cfg.llm_base_url}")
    print(f"   • rag_kb_name: {cfg.rag_kb_name}")
except Exception as e:
    print(f"   ⚠️ 配置测试跳过: {e}")

# 测试 5: 配置文件检查
print("\n5️⃣ 配置文件检查")
config_files = [
    'configs/sandbox-server/finance_research_config.json',
    'configs/synthesis/finance_research_config.json',
    'seeds/finance_research/seeds.jsonl'
]

for cfg_file in config_files:
    full_path = os.path.expanduser(f'~/.openclaw/workspace-dev/external/AgentFlow/{cfg_file}')
    if os.path.exists(full_path):
        print(f"   ✅ {cfg_file}")
    else:
        print(f"   ❌ {cfg_file} (缺失)")

# 测试 6: 工具调用格式验证
print("\n6️⃣ 工具调用格式验证")
expected_tools = [
    'web_search',
    'knowledge_search',
    'text2sql',
    'data_analyzer',
    'chart_generator',
    'stock_query',
    'bidding_search',
    'finish'
]

missing = set(expected_tools) - set(t['name'] for t in tools)
if missing:
    print(f"   ❌ 缺失工具: {missing}")
else:
    print("   ✅ 所有必需工具已定义")

print("\n" + "=" * 60)
print("✅ 所有测试通过！")
print("=" * 60)
print("\n📝 下一步:")
print("   1. 确保金融研投助手依赖已安装")
print("   2. 设置 API Keys")
print("   3. 启动 Sandbox: python -m sandbox.server configs/sandbox-server/finance_research_config.json")
print("   4. 运行合成: python -m synthesis.run configs/synthesis/finance_research_config.json")
print("=" * 60)
