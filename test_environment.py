#!/usr/bin/env python3
"""
AgentFlow 快速测试脚本
验证 deepresearch 环境是否能正常运行
"""

import sys
import os

# 添加 AgentFlow 到路径
sys.path.insert(0, os.path.expanduser('~/.openclaw/workspace-dev/external/AgentFlow'))

print("=" * 60)
print("🚀 AgentFlow 环境测试")
print("=" * 60)

# 测试 1: 导入核心模块
print("\n📦 测试 1: 导入核心模块")
try:
    from sandbox import Sandbox
    from synthesis import QASynthesizer, TrajectorySampler, synthesize
    from rollout import RolloutPipeline, rollout, quick_rollout
    print("   ✅ 所有核心模块导入成功")
except Exception as e:
    print(f"   ❌ 导入失败: {e}")
    sys.exit(1)

# 测试 2: 检查配置目录
print("\n📁 测试 2: 检查配置目录")
config_dirs = ['configs/synthesis', 'configs/rollout', 'configs/sandbox-server', 'seeds']
for dir_path in config_dirs:
    full_path = os.path.join(os.path.expanduser('~/.openclaw/workspace-dev/external/AgentFlow'), dir_path)
    if os.path.exists(full_path):
        print(f"   ✅ {dir_path}")
    else:
        print(f"   ⚠️  {dir_path} (不存在)")

# 测试 3: 检查可用的合成配置
print("\n🔧 测试 3: 可用的合成配置")
config_path = os.path.expanduser('~/.openclaw/workspace-dev/external/AgentFlow/configs/synthesis')
if os.path.exists(config_path):
    configs = [f for f in os.listdir(config_path) if f.endswith('.json')]
    for config in configs:
        print(f"   📄 {config}")

# 测试 4: 检查 seeds
print("\n🌱 测试 4: 可用的 seeds")
seeds_path = os.path.expanduser('~/.openclaw/workspace-dev/external/AgentFlow/seeds')
if os.path.exists(seeds_path):
    for seed_dir in os.listdir(seeds_path):
        seed_dir_path = os.path.join(seeds_path, seed_dir)
        if os.path.isdir(seed_dir_path):
            seeds_files = [f for f in os.listdir(seed_dir_path) if f.endswith('.jsonl')]
            if seeds_files:
                print(f"   📂 {seed_dir}/: {', '.join(seeds_files)}")

# 测试 5: Python 版本
print("\n🐍 测试 5: Python 环境")
print(f"   Python版本: {sys.version}")
print(f"   环境路径: {sys.executable}")

print("\n" + "=" * 60)
print("🎉 AgentFlow 环境测试完成！")
print("=" * 60)
print("\n💡 使用提示:")
print("   1. 配置 API Key: export OPENROUTER_API_KEY=your_key")
print("   2. 启动 sandbox: python -m sandbox.server configs/sandbox-server/rag_config.json")
print("   3. 运行合成: python -m synthesis.run configs/synthesis/rag_config.json")
print("=" * 60)
