#!/usr/bin/env python3
"""
验证轨迹是否符合系统编排两轮架构
"""
import sys
import os
import json
import asyncio
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))
os.chdir(_project_root)

from synthesis.core import SynthesisConfig
from synthesis.pipeline import SynthesisPipeline


def analyze_trajectory_structure(trajectory):
    """分析轨迹的工具调用结构"""
    nodes = trajectory.get('nodes', [])
    analysis = {
        'trajectory_id': trajectory.get('trajectory_id', 'unknown'),
        'total_depth': trajectory.get('total_depth', 0),
        'node_count': len(nodes),
        'tool_calls': [],
        'round1_skill_calls': [],
        'round2_tool_calls': [],
        'compliant': True,
        'issues': []
    }

    for i, node in enumerate(nodes):
        action = node.get('action', {})
        tool_name = action.get('tool_name', '')
        tool_input = action.get('tool_input', {})

        if not tool_name:
            continue

        tool_info = {
            'node_index': i,
            'tool_name': tool_name,
            'tool_input': tool_input
        }
        analysis['tool_calls'].append(tool_info)

        # 判断工具调用类型
        if tool_name == 'skill':
            analysis['round1_skill_calls'].append(tool_info)
        elif tool_name in ['get_skill_tools', 'execute_skill_tool']:
            # LLM 直接调用系统内部工具 - 这是错误的
            analysis['issues'].append(f"节点 {i}: 发现系统内部工具 '{tool_name}' 被 LLM 直接调用")
            analysis['compliant'] = False
        elif tool_name.startswith('unified_finance:'):
            # LLM 错误地调用了 unified_finance: 前缀的工具
            analysis['issues'].append(f"节点 {i}: LLM 不应直接调用 '{tool_name}'，应直接使用 skill_name.tool_name 格式")
            analysis['compliant'] = False
        elif '.' in tool_name or tool_name.startswith('market_data') or \
             tool_name.startswith('financial_analysis') or \
             tool_name.startswith('sector_analysis') or \
             tool_name.startswith('risk_assessment') or \
             tool_name.startswith('web_research') or \
             tool_name.startswith('data_analysis') or \
             tool_name.startswith('deep_research'):
            analysis['round2_tool_calls'].append(tool_info)

    # 验证调用顺序
    skill_call_indices = [t['node_index'] for t in analysis['round1_skill_calls']]
    tool_call_indices = [t['node_index'] for t in analysis['round2_tool_calls']]

    if not analysis['round1_skill_calls']:
        analysis['issues'].append("没有 Round 1 (skill) 调用")
        analysis['compliant'] = False

    if not analysis['round2_tool_calls']:
        analysis['issues'].append("没有 Round 2 (具体工具) 调用")
        analysis['compliant'] = False

    # 检查是否有工具调用在 skill 之前
    if skill_call_indices and tool_call_indices:
        first_skill = min(skill_call_indices)
        first_tool = min(tool_call_indices)
        if first_tool < first_skill:
            analysis['issues'].append(f"工具调用 ({first_tool}) 在 skill 选择 ({first_skill}) 之前")
            analysis['compliant'] = False

    return analysis


def print_analysis(analysis):
    """打印分析结果"""
    print(f"\n{'='*80}")
    print(f"轨迹分析: {analysis['trajectory_id']}")
    print(f"{'='*80}")
    print(f"总深度: {analysis['total_depth']}")
    print(f"节点数: {analysis['node_count']}")
    print(f"工具调用总数: {len(analysis['tool_calls'])}")

    print(f"\nRound 1 (Skill 选择): {len(analysis['round1_skill_calls'])} 次")
    for call in analysis['round1_skill_calls']:
        print(f"  节点 {call['node_index']}: skill({call['tool_input']})")

    print(f"\nRound 2 (具体工具调用): {len(analysis['round2_tool_calls'])} 次")
    for call in analysis['round2_tool_calls']:
        print(f"  节点 {call['node_index']}: {call['tool_name']}")

    # 验证系统编排架构
    print(f"\n系统编排架构验证:")
    print(f"  - Round 1: LLM 调用 skill() 选择技能")
    print(f"  - 系统内部: 自动调用 get_skill_tools 获取工具列表")
    print(f"  - Round 2: LLM 直接调用 skill_name.tool_name 格式工具")
    print(f"  - 系统内部: 自动转换为 execute_skill_tool 执行")

    if analysis['compliant']:
        print(f"\n✅ 符合系统编排两轮架构")
    else:
        print(f"\n❌ 不符合预期架构")
        for issue in analysis['issues']:
            print(f"   - {issue}")


async def main():
    print("="*80)
    print("轨迹生成与验证测试")
    print("="*80)

    # 加载配置
    config = SynthesisConfig.from_json("configs/synthesis/finance_research_config.json")
    config.number_of_seed = 3  # 测试 3 个种子
    config.max_depth = 5
    config.branching_factor = 2
    config.max_selected_traj = 2
    # 禁用 auto_start，确保使用已运行的服务器
    config.sandbox_auto_start = False
    config.sandbox_server_url = "http://127.0.0.1:8080"

    print(f"\n配置:")
    print(f"  Model: {config.model_name}")
    print(f"  Max depth: {config.max_depth}")
    print(f"  Seeds: {config.number_of_seed}")
    print(f"  Sandbox URL: {config.sandbox_server_url}")
    print(f"  Auto start: {config.sandbox_auto_start}")

    print(f"\n配置:")
    print(f"  Model: {config.model_name}")
    print(f"  Max depth: {config.max_depth}")
    print(f"  Seeds: {config.number_of_seed}")

    # 清理输出目录
    output_dir = "results/trajectory_validation_test"
    os.makedirs(output_dir, exist_ok=True)
    for f in ["synthesized_qa.jsonl", "trajectories.jsonl"]:
        p = os.path.join(output_dir, f)
        if os.path.exists(p):
            os.unlink(p)

    # 测试种子
    seeds = [
        {"content": "分析贵州茅台(600519)的投资价值", "kwargs": {}},
        {"content": "宁德时代(300750)的财务状况如何？", "kwargs": {}},
        {"content": "比较白酒行业龙头股的估值水平", "kwargs": {}}
    ]

    # 运行合成
    print("\n🚀 开始生成轨迹...")
    pipeline = SynthesisPipeline(config=config, output_dir=output_dir)
    await pipeline.run_async(seeds)

    # 分析生成的轨迹
    print("\n📊 分析生成的轨迹...")
    traj_file = Path(output_dir) / "trajectories.jsonl"

    if not traj_file.exists():
        print(f"❌ 未找到轨迹文件: {traj_file}")
        return

    trajectories = []
    with open(traj_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                trajectories.append(json.loads(line))

    print(f"\n共生成 {len(trajectories)} 条轨迹")

    compliant_count = 0
    for traj in trajectories:
        analysis = analyze_trajectory_structure(traj)
        print_analysis(analysis)
        if analysis['compliant']:
            compliant_count += 1

    print(f"\n{'='*80}")
    print(f"总结: {compliant_count}/{len(trajectories)} 条轨迹符合系统编排两轮架构")
    print(f"{'='*80}")


if __name__ == "__main__":
    asyncio.run(main())
