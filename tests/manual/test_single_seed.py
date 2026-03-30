#!/usr/bin/env python3
"""
快速单种子测试 - 验证渐进式披露流程
"""
import sys
import os
import json
import asyncio

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, str(_project_root))

os.chdir(_project_root)

print("="*80)
print("快速单种子测试 - 渐进式披露流程验证")
print("="*80)

from synthesis.core import SynthesisConfig
from synthesis.pipeline import SynthesisPipeline

async def test():
    config = SynthesisConfig.from_json("configs/synthesis/finance_research_config.json")
    config.number_of_seed = 1  # 只测试 1 个种子
    config.max_depth = 5  # 减少深度以加快测试
    config.branching_factor = 2
    
    print(f"✅ 配置加载成功")
    print(f"   Model: {config.model_name}")
    print(f"   Max depth: {config.max_depth}")
    print(f"   Seeds: {config.number_of_seed}")
    
    # 清理输出
    output_dir = "results/finance_research"
    os.makedirs(output_dir, exist_ok=True)
    for f in ["synthesized_qa.jsonl", "trajectories.jsonl"]:
        p = os.path.join(output_dir, f)
        if os.path.exists(p):
            os.unlink(p)
    
    # 单种子
    seeds = [{"content": "分析贵州茅台(600519)的投资价值", "kwargs": {}}]
    
    pipeline = SynthesisPipeline(config=config, output_dir=output_dir)
    
    print("\n🚀 开始测试...\n")
    await pipeline.run_async(seeds)
    
    print("\n" + "="*80)
    print("测试完成!")
    print("="*80)

asyncio.run(test())
