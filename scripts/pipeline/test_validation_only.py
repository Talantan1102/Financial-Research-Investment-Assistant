#!/usr/bin/env python3
"""
快速测试验证功能 - 使用现有数据
"""
import json
import sys
from pathlib import Path

# Add project root to path
_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))

from scripts.pipeline.convert_to_grpo import convert_to_grpo_format, print_grpo_example, analyze_grpo_data


def check_progressive_disclosure(traj):
    """检查渐进式披露流程"""
    nodes = traj.get('nodes', [])
    if not nodes:
        return {"compliant": False, "reason": "空轨迹", "violations": []}

    violations = []
    skill_calls = []
    get_skill_tools_calls = []
    execute_calls = []

    for i, node in enumerate(nodes):
        action = node.get('action', {})
        tool_name = action.get('tool_name', '')

        if not tool_name:
            continue

        # 解析工具名
        if ':' in tool_name:
            _, tool = tool_name.split(':', 1)
        elif '.' in tool_name:
            _, tool = tool_name.split('.', 1)
        else:
            tool = tool_name

        if tool == 'skill':
            skill_calls.append({"node_index": i, "tool_name": tool_name})
        elif tool == 'get_skill_tools':
            get_skill_tools_calls.append({"node_index": i, "tool_name": tool_name})
        elif tool == 'execute_skill_tool':
            execute_calls.append({"node_index": i, "tool_name": tool_name})

    # 检查违规
    if not execute_calls:
        violations.append("没有 execute_skill_tool 调用")

    if execute_calls and not skill_calls:
        violations.append("跳过 skill 直接调用 execute_skill_tool")

    if execute_calls and not get_skill_tools_calls:
        violations.append("跳过 get_skill_tools 直接调用 execute_skill_tool")

    for execute in execute_calls:
        exec_index = execute["node_index"]
        preceding_skills = [s for s in skill_calls if s["node_index"] < exec_index]
        preceding_get_tools = [g for g in get_skill_tools_calls if g["node_index"] < exec_index]

        if not preceding_skills:
            violations.append(f"节点 {exec_index} 的 execute_skill_tool 之前没有 skill 调用")
        if not preceding_get_tools:
            violations.append(f"节点 {exec_index} 的 execute_skill_tool 之前没有 get_skill_tools 调用")

    stats = {
        "skill_calls": len(skill_calls),
        "get_skill_tools_calls": len(get_skill_tools_calls),
        "execute_skill_tool_calls": len(execute_calls)
    }

    compliant = len(violations) == 0
    return {
        "compliant": compliant,
        "reason": "符合渐进式披露流程" if compliant else "; ".join(violations[:2]),
        "violations": violations,
        "stats": stats
    }


def analyze_trajectory_quality(traj):
    """分析轨迹质量"""
    nodes = traj.get('nodes', [])
    total_depth = traj.get('total_depth', 0)

    tool_names = []
    for node in nodes:
        action = node.get('action', {})
        tool_name = action.get('tool_name', '')
        if tool_name:
            tool_names.append(tool_name)

    unique_tools = set(tool_names)
    total_observation_length = sum(len(node.get('observation', '')) for node in nodes)
    avg_observation_length = total_observation_length / len(nodes) if nodes else 0

    return {
        "trajectory_id": traj.get('trajectory_id', ''),
        "depth": total_depth,
        "node_count": len(nodes),
        "tool_call_count": len(tool_names),
        "unique_tools": list(unique_tools),
        "tool_diversity": len(unique_tools),
        "avg_observation_length": round(avg_observation_length, 1)
    }


def main():
    output_dir = "results/grpo_sample_test"
    qa_file = Path(output_dir) / "synthesized_qa.jsonl"
    traj_file = Path(output_dir) / "trajectories.jsonl"

    print("="*80)
    print("测试验证功能 - 使用现有数据")
    print("="*80)

    # 加载数据
    print("\n1. 加载数据...")
    trajectories = []
    with open(traj_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                trajectories.append(json.loads(line))

    qa_pairs = []
    with open(qa_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                qa_pairs.append(json.loads(line))

    print(f"   加载了 {len(trajectories)} 条轨迹")
    print(f"   加载了 {len(qa_pairs)} 个 QA 对")

    # 渐进式披露检查
    print("\n2. 渐进式披露流程检查...")
    compliant_count = 0
    for i, traj in enumerate(trajectories[:5]):  # 只检查前5条
        result = check_progressive_disclosure(traj)
        status = "✅" if result['compliant'] else "❌"
        print(f"   {status} 轨迹 {i+1}: {result['reason']}")
        print(f"      工具调用: skill={result['stats']['skill_calls']}, "
              f"get_skill_tools={result['stats']['get_skill_tools_calls']}, "
              f"execute={result['stats']['execute_skill_tool_calls']}")
        if result['compliant']:
            compliant_count += 1

    print(f"\n   合规率: {compliant_count}/5 ({compliant_count*20}%)")

    # 轨迹质量分析
    print("\n3. 轨迹质量分析...")
    depths = []
    tool_counts = []
    diversities = []

    for traj in trajectories[:5]:
        quality = analyze_trajectory_quality(traj)
        depths.append(quality['depth'])
        tool_counts.append(quality['tool_call_count'])
        diversities.append(quality['tool_diversity'])

    print(f"   平均深度: {sum(depths)/len(depths):.1f}")
    print(f"   平均工具调用数: {sum(tool_counts)/len(tool_counts):.1f}")
    print(f"   平均工具多样性: {sum(diversities)/len(diversities):.1f}")

    # 转换为 GRPO 格式
    print("\n4. 转换为 GRPO 格式...")
    grpo_file = Path(output_dir) / "grpo_data.jsonl"
    grpo_data = convert_to_grpo_format(qa_file, traj_file, grpo_file)

    # 显示 GRPO 统计
    print("\n5. GRPO 数据统计...")
    analyze_grpo_data(grpo_data)

    # 显示第一个样例
    print("\n6. GRPO 样例展示...")
    print_grpo_example(grpo_data, 0)

    print("\n" + "="*80)
    print("测试完成!")
    print("="*80)


if __name__ == "__main__":
    main()
