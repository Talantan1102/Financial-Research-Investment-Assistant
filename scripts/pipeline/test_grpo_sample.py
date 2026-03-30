#!/usr/bin/env python3
"""
随机抽样 Seed 测试 GRPO 轨迹生成质量

功能：
1. 随机抽样 N 个种子
2. 使用轻量配置运行轨迹生成和 QA 合成
3. 转换为 GRPO 格式
4. 验证轨迹质量和渐进式披露流程

Usage:
    python scripts/pipeline/test_grpo_sample.py --num-seeds 5 --config configs/synthesis/grpo_100k_config.json
"""

import argparse
import asyncio
import json
import os
import random
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

# Add project root to path
_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))

# Check dependencies
try:
    from synthesis.api import load_config, load_seeds
    from synthesis.pipeline import SynthesisPipeline
    from scripts.pipeline.convert_to_grpo import convert_to_grpo_format, print_grpo_example, analyze_grpo_data
except ImportError as e:
    print(f"错误: 缺少依赖项 - {e}")
    print("\n请安装依赖:")
    print("    bash install.sh")
    print("\n或仅安装核心依赖:")
    print("    pip install pyyaml fastapi pydantic openai httpx")
    sys.exit(1)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="随机抽样 Seed 测试 GRPO 轨迹生成质量",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    # 测试 5 个随机种子
    python scripts/pipeline/test_grpo_sample.py

    # 测试 10 个随机种子，使用自定义配置
    python scripts/pipeline/test_grpo_sample.py --num-seeds 10 --config configs/synthesis/grpo_100k_config.json

    # 指定随机种子以保证可复现
    python scripts/pipeline/test_grpo_sample.py --num-seeds 5 --seed 42
        """
    )
    parser.add_argument(
        "--num-seeds", "-n",
        type=int,
        default=5,
        help="随机抽样的种子数量 (默认: 5)"
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default="configs/synthesis/grpo_100k_config.json",
        help="配置文件路径 (默认: configs/synthesis/grpo_100k_config.json)"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="随机种子，用于可复现抽样 (默认: None)"
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default="results/grpo_sample_test",
        help="输出目录 (默认: results/grpo_sample_test)"
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=5,
        help="轨迹最大深度 (默认: 5)"
    )
    parser.add_argument(
        "--branching-factor",
        type=int,
        default=2,
        help="分支因子 (默认: 2)"
    )
    parser.add_argument(
        "--max-selected-traj",
        type=int,
        default=2,
        help="每个种子选择的最大轨迹数 (默认: 2)"
    )

    return parser.parse_args()


def sample_random_seeds(seeds_file: str, num_seeds: int, random_seed: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    从种子文件中随机抽样

    Args:
        seeds_file: 种子文件路径 (JSONL 格式)
        num_seeds: 抽样数量
        random_seed: 随机种子（用于可复现）

    Returns:
        抽样后的种子列表
    """
    if random_seed is not None:
        random.seed(random_seed)

    # 加载所有种子
    all_seeds = []
    with open(seeds_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                seed = json.loads(line)
                if isinstance(seed, dict) and "content" in seed:
                    # Handle different seed formats
                    if "kwargs" not in seed:
                        seed["kwargs"] = {}
                    # Copy slots and entities to kwargs if present
                    if "slots" in seed:
                        seed["kwargs"]["slots"] = seed.pop("slots")
                    if "entities" in seed:
                        seed["kwargs"]["entities"] = seed.pop("entities")
                    if "task_id" in seed:
                        seed["kwargs"]["task_id"] = seed.pop("task_id")
                    all_seeds.append(seed)

    if not all_seeds:
        raise ValueError(f"没有找到有效的种子: {seeds_file}")

    print(f"   种子文件共包含 {len(all_seeds)} 个种子")

    # 随机抽样
    if num_seeds >= len(all_seeds):
        print(f"   警告: 请求 {num_seeds} 个种子，但文件只有 {len(all_seeds)} 个")
        return all_seeds

    sampled = random.sample(all_seeds, num_seeds)
    print(f"   随机抽样 {num_seeds} 个种子")

    # 显示抽样的种子内容预览
    print("\n   抽样种子预览:")
    for i, seed in enumerate(sampled, 1):
        content = seed["content"]
        preview = content[:50] + "..." if len(content) > 50 else content
        print(f"      {i}. {preview}")

    return sampled


async def run_synthesis_with_config(
    config_path: str,
    seeds: List[Dict[str, Any]],
    output_dir: str,
    max_depth: int = 5,
    branching_factor: int = 2,
    max_selected_traj: int = 2
) -> Tuple[Path, Path]:
    """
    使用修改后的配置运行合成管道

    Args:
        config_path: 配置文件路径
        seeds: 种子列表
        output_dir: 输出目录
        max_depth: 轨迹最大深度
        branching_factor: 分支因子
        max_selected_traj: 每个种子选择的最大轨迹数

    Returns:
        (synthesized_qa 文件路径, trajectories 文件路径)
    """
    # 加载配置
    config = load_config(config_path)

    # 覆写轻量参数
    config.number_of_seed = len(seeds)
    config.max_depth = max_depth
    config.branching_factor = branching_factor
    config.max_selected_traj = max_selected_traj
    config.output_dir = output_dir

    # 确保输出目录存在并清理旧文件
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 清理旧的输出文件
    for f in ["synthesized_qa.jsonl", "trajectories.jsonl"]:
        p = output_path / f
        if p.exists():
            p.unlink()

    print(f"   配置参数:")
    print(f"      - number_of_seed: {config.number_of_seed}")
    print(f"      - max_depth: {config.max_depth}")
    print(f"      - branching_factor: {config.branching_factor}")
    print(f"      - max_selected_traj: {config.max_selected_traj}")
    print(f"      - output_dir: {output_dir}")

    # 创建并运行管道
    pipeline = SynthesisPipeline(config=config, output_dir=output_dir)

    # 运行合成 (直接使用 await)
    await pipeline.run_async(seeds)

    qa_file = output_path / "synthesized_qa.jsonl"
    traj_file = output_path / "trajectories.jsonl"

    return qa_file, traj_file


def check_progressive_disclosure(traj: Dict[str, Any]) -> Dict[str, Any]:
    """
    检查轨迹是否遵循渐进式披露流程

    期望的流程：
    - Round 1: skill(name="xxx")
    - Round 2: get_skill_tools(name="xxx")
    - Round 3: execute_skill_tool(...)

    Args:
        traj: 轨迹字典

    Returns:
        检查结果字典
    """
    nodes = traj.get('nodes', [])
    if not nodes:
        return {
            "compliant": False,
            "reason": "空轨迹",
            "violations": []
        }

    violations = []
    has_skill = False
    has_get_skill_tools = False
    has_execute_skill_tool = False

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

        # 记录工具调用
        if tool == 'skill':
            has_skill = True
            skill_calls.append({
                "node_index": i,
                "tool_name": tool_name,
                "parameters": action.get('parameters', {})
            })
        elif tool == 'get_skill_tools':
            has_get_skill_tools = True
            get_skill_tools_calls.append({
                "node_index": i,
                "tool_name": tool_name,
                "parameters": action.get('parameters', {})
            })
        elif tool == 'execute_skill_tool':
            has_execute_skill_tool = True
            execute_calls.append({
                "node_index": i,
                "tool_name": tool_name,
                "parameters": action.get('parameters', {})
            })

    # 检查渐进式披露合规性
    # 理想情况下，应该看到：skill -> get_skill_tools -> execute_skill_tool 的顺序

    # 基本合规：至少有一个 execute_skill_tool 调用
    if not has_execute_skill_tool:
        violations.append("没有 execute_skill_tool 调用")

    # 检查调用顺序问题
    if has_execute_skill_tool and not has_skill:
        violations.append("跳过 skill 直接调用 execute_skill_tool")

    if has_execute_skill_tool and not has_get_skill_tools:
        violations.append("跳过 get_skill_tools 直接调用 execute_skill_tool")

    # 检查 skill 和 get_skill_tools 的顺序
    for execute in execute_calls:
        exec_index = execute["node_index"]

        # 这个 execute 调用之前应该有 skill 和 get_skill_tools
        preceding_skills = [s for s in skill_calls if s["node_index"] < exec_index]
        preceding_get_tools = [g for g in get_skill_tools_calls if g["node_index"] < exec_index]

        if not preceding_skills:
            violations.append(f"节点 {exec_index} 的 execute_skill_tool 之前没有 skill 调用")
        if not preceding_get_tools:
            violations.append(f"节点 {exec_index} 的 execute_skill_tool 之前没有 get_skill_tools 调用")

    # 统计
    stats = {
        "skill_calls": len(skill_calls),
        "get_skill_tools_calls": len(get_skill_tools_calls),
        "execute_skill_tool_calls": len(execute_calls),
        "skill_details": skill_calls,
        "get_skill_tools_details": get_skill_tools_calls,
        "execute_details": execute_calls
    }

    compliant = len(violations) == 0

    return {
        "compliant": compliant,
        "reason": "符合渐进式披露流程" if compliant else "; ".join(violations),
        "violations": violations,
        "stats": stats
    }


def analyze_trajectory_quality(traj: Dict[str, Any]) -> Dict[str, Any]:
    """
    分析单条轨迹的质量指标

    Args:
        traj: 轨迹字典

    Returns:
        质量分析结果
    """
    nodes = traj.get('nodes', [])
    total_depth = traj.get('total_depth', 0)

    # 工具调用统计
    tool_names = []
    tool_calls = []

    for node in nodes:
        action = node.get('action', {})
        tool_name = action.get('tool_name', '')
        if tool_name:
            tool_names.append(tool_name)
            tool_calls.append({
                "tool_name": tool_name,
                "parameters": action.get('parameters', {}),
                "intent": node.get('intent', '')
            })

    # 工具多样性
    unique_tools = set(tool_names)

    # 观察丰富度（观察文本长度）
    total_observation_length = sum(
        len(node.get('observation', ''))
        for node in nodes
    )
    avg_observation_length = total_observation_length / len(nodes) if nodes else 0

    return {
        "trajectory_id": traj.get('trajectory_id', ''),
        "depth": total_depth,
        "node_count": len(nodes),
        "tool_call_count": len(tool_names),
        "unique_tools": list(unique_tools),
        "tool_diversity": len(unique_tools),
        "total_observation_length": total_observation_length,
        "avg_observation_length": round(avg_observation_length, 1)
    }


def check_qa_quality(qa: Dict[str, Any]) -> Dict[str, Any]:
    """
    检查 QA 对的质量

    Args:
        qa: QA 字典

    Returns:
        质量检查结果
    """
    question = qa.get('question', '')
    answer = qa.get('answer', '')
    reasoning_steps = qa.get('reasoning_steps', [])

    issues = []

    # 检查问题质量
    question_length = len(question)
    if question_length < 10:
        issues.append("问题太短")

    # 检查答案质量
    has_no_info = '未提供' in answer or '无法' in answer or '没有' in answer
    answer_length = len(answer)

    if has_no_info:
        issues.append("答案包含'未提供'或类似表述")
    if answer_length < 20:
        issues.append("答案太短")

    # reasoning_steps 质量
    steps_count = len(reasoning_steps)

    return {
        "qa_id": qa.get('qa_id', ''),
        "trajectory_id": qa.get('trajectory_id', ''),
        "question_length": question_length,
        "answer_length": answer_length,
        "has_no_info": has_no_info,
        "reasoning_steps_count": steps_count,
        "quality_issues": issues,
        "pass": len(issues) == 0
    }


def generate_validation_report(
    trajectories: List[Dict[str, Any]],
    qa_pairs: List[Dict[str, Any]],
    grpo_data: List[Dict[str, Any]],
    output_dir: str
) -> Dict[str, Any]:
    """
    生成验证报告

    Args:
        trajectories: 轨迹列表
        qa_pairs: QA 列表
        grpo_data: GRPO 格式数据
        output_dir: 输出目录

    Returns:
        报告字典
    """
    print("\n" + "="*80)
    print("生成验证报告")
    print("="*80)

    # 1. 摘要统计
    summary = {
        "total_seeds": len(set(t.get('source_id', '') for t in trajectories)),
        "total_trajectories": len(trajectories),
        "total_qa": len(qa_pairs),
        "avg_depth": 0,
        "avg_tool_calls": 0,
        "avg_tool_diversity": 0
    }

    if trajectories:
        depths = []
        tool_counts = []
        diversities = []

        for traj in trajectories:
            quality = analyze_trajectory_quality(traj)
            depths.append(quality['depth'])
            tool_counts.append(quality['tool_call_count'])
            diversities.append(quality['tool_diversity'])

        summary['avg_depth'] = round(sum(depths) / len(depths), 2)
        summary['avg_tool_calls'] = round(sum(tool_counts) / len(tool_counts), 2)
        summary['avg_tool_diversity'] = round(sum(diversities) / len(diversities), 2)

    print(f"\n📊 摘要统计:")
    print(f"   - 涉及种子数: {summary['total_seeds']}")
    print(f"   - 生成轨迹数: {summary['total_trajectories']}")
    print(f"   - 生成 QA 数: {summary['total_qa']}")
    print(f"   - 平均深度: {summary['avg_depth']}")
    print(f"   - 平均工具调用数: {summary['avg_tool_calls']}")
    print(f"   - 平均工具多样性: {summary['avg_tool_diversity']}")

    # 2. 渐进式披露检查
    print(f"\n🔍 渐进式披露流程检查:")
    pd_checks = []
    compliant_count = 0

    for traj in trajectories:
        traj_id = traj.get('trajectory_id', '')
        result = check_progressive_disclosure(traj)
        result['trajectory_id'] = traj_id
        pd_checks.append(result)

        if result['compliant']:
            compliant_count += 1
            status = "✅"
        else:
            status = "❌"

        print(f"   {status} {traj_id[:30]}... - {result['reason']}")

        # 如果有违规，打印详细信息
        if result['violations']:
            for v in result['violations']:
                print(f"      ⚠️  {v}")

    pd_summary = {
        "total_checked": len(trajectories),
        "compliant": compliant_count,
        "non_compliant": len(trajectories) - compliant_count,
        "compliance_rate": round(compliant_count / len(trajectories) * 100, 1) if trajectories else 0,
        "details": pd_checks
    }

    print(f"\n   合规率: {pd_summary['compliance_rate']}% ({compliant_count}/{len(trajectories)})")

    # 3. QA 质量检查
    print(f"\n📝 QA 质量检查:")
    qa_checks = []
    pass_count = 0

    for qa in qa_pairs:
        result = check_qa_quality(qa)
        qa_checks.append(result)

        if result['pass']:
            pass_count += 1

    qa_summary = {
        "total_checked": len(qa_pairs),
        "passed": pass_count,
        "failed": len(qa_pairs) - pass_count,
        "pass_rate": round(pass_count / len(qa_pairs) * 100, 1) if qa_pairs else 0,
        "details": qa_checks
    }

    print(f"   通过率: {qa_summary['pass_rate']}% ({pass_count}/{len(qa_pairs)})")
    print(f"   平均 reasoning_steps: {sum(q['reasoning_steps_count'] for q in qa_checks) / len(qa_checks) if qa_checks else 0:.1f}")

    # 4. 样例 GRPO messages
    sample_messages = None
    if grpo_data:
        first_item = grpo_data[0]
        sample_messages = first_item.get('messages', [])

        print(f"\n📨 第一个 GRPO 样本的 messages:")
        print(f"   共 {len(sample_messages)} 条消息")
        for i, msg in enumerate(sample_messages[:5], 1):  # 只显示前5条
            content = msg.get('content', '')
            preview = content[:80] + "..." if len(content) > 80 else content
            print(f"      {i}. [{msg.get('role', '')}] {preview}")

        if len(sample_messages) > 5:
            print(f"      ... 还有 {len(sample_messages) - 5} 条消息")

    # 组合报告
    report = {
        "summary": summary,
        "progressive_disclosure_check": pd_summary,
        "qa_quality_check": qa_summary,
        "sample_grpo_messages": sample_messages
    }

    # 保存报告
    report_path = Path(output_dir) / "validation_report.json"
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n📄 报告已保存: {report_path}")

    return report


async def main_async(args: argparse.Namespace):
    """异步主函数"""
    print("="*80)
    print("随机抽样 Seed 测试 GRPO 轨迹生成质量")
    print("="*80)
    print(f"\n参数:")
    print(f"   - 抽样数量: {args.num_seeds}")
    print(f"   - 配置文件: {args.config}")
    print(f"   - 随机种子: {args.seed}")
    print(f"   - 输出目录: {args.output_dir}")
    print(f"   - max_depth: {args.max_depth}")
    print(f"   - branching_factor: {args.branching_factor}")
    print(f"   - max_selected_traj: {args.max_selected_traj}")

    # 1. 加载配置并获取种子文件路径
    print("\n" + "-"*80)
    print("步骤 1: 加载配置")
    print("-"*80)

    config = load_config(args.config)
    seeds_file = config.seeds_file or "data/seeds/seeds_100k_all.jsonl"

    if not Path(seeds_file).exists():
        raise FileNotFoundError(f"种子文件不存在: {seeds_file}")

    print(f"   种子文件: {seeds_file}")

    # 2. 随机抽样种子
    print("\n" + "-"*80)
    print("步骤 2: 随机抽样种子")
    print("-"*80)

    sampled_seeds = sample_random_seeds(seeds_file, args.num_seeds, args.seed)

    # 3. 运行合成管道
    print("\n" + "-"*80)
    print("步骤 3: 运行合成管道")
    print("-"*80)

    qa_file, traj_file = await run_synthesis_with_config(
        config_path=args.config,
        seeds=sampled_seeds,
        output_dir=args.output_dir,
        max_depth=args.max_depth,
        branching_factor=args.branching_factor,
        max_selected_traj=args.max_selected_traj
    )

    print(f"\n   ✅ 合成完成")
    print(f"      - QA 文件: {qa_file}")
    print(f"      - 轨迹文件: {traj_file}")

    # 4. 转换为 GRPO 格式
    print("\n" + "-"*80)
    print("步骤 4: 转换为 GRPO 格式")
    print("-"*80)

    grpo_file = Path(args.output_dir) / "grpo_data.jsonl"
    grpo_data = convert_to_grpo_format(qa_file, traj_file, grpo_file)

    # 5. 加载数据并生成验证报告
    print("\n" + "-"*80)
    print("步骤 5: 质量验证")
    print("-"*80)

    # 加载轨迹和 QA
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

    # 生成验证报告
    report = generate_validation_report(
        trajectories=trajectories,
        qa_pairs=qa_pairs,
        grpo_data=grpo_data,
        output_dir=args.output_dir
    )

    # 6. 输出结果摘要
    print("\n" + "="*80)
    print("测试完成!")
    print("="*80)
    print(f"\n输出文件:")
    print(f"   - QA 数据: {qa_file}")
    print(f"   - 轨迹数据: {traj_file}")
    print(f"   - GRPO 数据: {grpo_file}")
    print(f"   - 验证报告: {Path(args.output_dir) / 'validation_report.json'}")

    print(f"\n关键指标:")
    print(f"   - 轨迹数: {report['summary']['total_trajectories']}")
    print(f"   - QA 数: {report['summary']['total_qa']}")
    print(f"   - 渐进式披露合规率: {report['progressive_disclosure_check']['compliance_rate']}%")
    print(f"   - QA 质量通过率: {report['qa_quality_check']['pass_rate']}%")

    # 7. 显示第一个 GRPO 样例
    print("\n" + "-"*80)
    print("GRPO 样例展示")
    print("-"*80)
    analyze_grpo_data(grpo_data)
    print()
    print_grpo_example(grpo_data, 0)

    return report


def main():
    """主函数"""
    args = parse_args()

    # 切换到项目根目录
    os.chdir(_project_root)

    # 运行异步主函数
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
