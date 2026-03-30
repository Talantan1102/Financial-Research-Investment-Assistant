#!/usr/bin/env python3
"""
完整数据合成流程测试
"""
import sys
import os
import json
import asyncio
from pathlib import Path

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, str(_project_root))

# 设置工作目录
os.chdir(_project_root)

print("="*80)
print("AgentFlow 完整数据合成流程测试")
print("="*80)

# 检查种子数据
seeds_path = "seeds/finance_research/test_seeds.jsonl"
if not Path(seeds_path).exists():
    print(f"❌ 种子文件不存在: {seeds_path}")
    sys.exit(1)

with open(seeds_path, 'r') as f:
    seeds = [json.loads(line) for line in f if line.strip()]
print(f"✅ 加载种子数据: {len(seeds)} 条")
for i, seed in enumerate(seeds[:3], 1):
    print(f"   {i}. {seed.get('content', '')[:50]}...")

# 检查输出目录
output_dir = "results/finance_research"
os.makedirs(output_dir, exist_ok=True)
print(f"✅ 输出目录: {output_dir}")

# 清理之前的输出文件
qa_file = Path(output_dir) / "synthesized_qa.jsonl"
traj_file = Path(output_dir) / "trajectories.jsonl"
if qa_file.exists():
    qa_file.unlink()
    print(f"   清理旧 QA 文件")
if traj_file.exists():
    traj_file.unlink()
    print(f"   清理旧 Trajectory 文件")

print("\n" + "="*80)
print("开始数据合成...")
print("="*80)

# 导入并运行 pipeline
from synthesis.core import SynthesisConfig
from synthesis.pipeline import SynthesisPipeline

async def run_synthesis():
    # 加载配置
    config = SynthesisConfig.from_json("configs/synthesis/finance_research_config.json")
    print(f"✅ 配置加载成功")
    print(f"   Model: {config.model_name}")
    print(f"   Max depth: {config.max_depth}")
    print(f"   Branching factor: {config.branching_factor}")
    print(f"   Number of seeds: {config.number_of_seed or 'all'}")
    
    # 创建 pipeline
    pipeline = SynthesisPipeline(config=config, output_dir=output_dir)
    
    # 加载种子
    seeds = []
    with open(seeds_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                seed = json.loads(line)
                if isinstance(seed, dict):
                    if "content" not in seed:
                        raise ValueError(f"Seed missing 'content' field: {seed}")
                    if "kwargs" not in seed:
                        seed["kwargs"] = {}
                    seeds.append(seed)
    
    print(f"\n🚀 开始处理 {len(seeds[:config.number_of_seed or len(seeds)])} 个种子...\n")
    
    # 运行合成
    try:
        await pipeline.run_async(seeds)
        print("\n✅ 数据合成完成!")
    except Exception as e:
        print(f"\n❌ 数据合成失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

# 运行
success = asyncio.run(run_synthesis())

# 检查结果
print("\n" + "="*80)
print("检查结果...")
print("="*80)

if qa_file.exists():
    with open(qa_file, 'r') as f:
        qa_count = sum(1 for _ in f)
    print(f"✅ QA 文件: {qa_file} ({qa_count} 条)")
else:
    print(f"❌ QA 文件不存在")
    qa_count = 0

if traj_file.exists():
    with open(traj_file, 'r') as f:
        traj_count = sum(1 for _ in f)
    print(f"✅ Trajectory 文件: {traj_file} ({traj_count} 条)")
else:
    print(f"❌ Trajectory 文件不存在")
    traj_count = 0

# 显示示例
if qa_count > 0:
    print("\n" + "="*80)
    print("生成的 QA 示例:")
    print("="*80)
    with open(qa_file, 'r') as f:
        first_qa = json.loads(f.readline())
        print(f"\n问题: {first_qa.get('question', 'N/A')[:200]}...")
        print(f"\n答案: {first_qa.get('answer', 'N/A')[:300]}...")
        if 'trajectory' in first_qa:
            traj = first_qa['trajectory']
            print(f"\n轨迹节点数: {len(traj) if isinstance(traj, list) else 'N/A'}")

print("\n" + "="*80)
if success and qa_count > 0:
    print("🎉 完整数据合成流程测试成功!")
else:
    print("❌ 测试未完成，请检查日志")
print("="*80)

sys.exit(0 if success else 1)
