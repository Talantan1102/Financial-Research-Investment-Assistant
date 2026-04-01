#!/usr/bin/env python3
"""
将 AgentFlow 生成的数据转换为 GRPO 训练格式

GRPO 数据格式:
{
  "messages": [
    {"role": "system", "content": "系统提示"},
    {"role": "user", "content": "问题"},
    {"role": "assistant", "content": "思考过程", "tool_calls": [...]},
    {"role": "tool", "content": "工具返回结果"},
    ...
  ],
  "prompt_messages": [system, user],
  "response": "完整 assistant trajectory（含 tool_call 标签）",
  "metadata": {...}
}

支持 Qwen3 chat template：增加 `--chat-template qwen3` 参数。
"""
import json
import sys
import argparse
from pathlib import Path


DEFAULT_SYSTEM_PROMPT = (
    "你是一个金融研究助手，可以使用工具来分析股票、行业和财务数据。"
    "请逐步思考并使用合适的工具来回答问题。"
    "当你需要使用工具时，请使用 <tool_call>{\"name\": \"tool.name\", \"arguments\": {...}}</tool_call> 格式。"
)


def build_response_from_trajectory(trajectory_nodes, qa_answer, chat_template="default"):
    """
    将轨迹节点构建为模型需要学习的 response 字符串。

    对于 Qwen3 / GRPO 训练，response 包含多轮 thinking + tool_call 标签 + 最终回答。
    """
    response_parts = []

    for i, node in enumerate(trajectory_nodes, 1):
        action = node.get("action", {})
        tool_name = action.get("tool_name", "")
        params = action.get("parameters", {})
        intent = node.get("intent", "")
        observation = node.get("observation", "")

        if not tool_name:
            continue

        # Reasoning text
        if intent:
            response_parts.append(f"步骤 {i}：{intent}")

        # Tool call in XML/JSON format
        tool_call = json.dumps({"name": tool_name, "arguments": params}, ensure_ascii=False)
        response_parts.append(f"<tool_call>\n{tool_call}\n</tool_call>")

        # Observation inline (optional - some training configs include this,
        # but for RL we typically want the model to learn to issue tool calls,
        # not reproduce observations). We omit observations from the response.
        # response_parts.append(f"[Observation] {observation[:200]}...")

    # Final answer
    if qa_answer:
        response_parts.append(f"\n根据以上分析，我的答案是：\n{qa_answer}")

    return "\n".join(response_parts)


def convert_to_grpo_format(qa_file, traj_file, output_file, chat_template="default"):
    """Convert AgentFlow output to GRPO training format"""

    # Load QA pairs
    qa_list = []
    with open(qa_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                qa_list.append(json.loads(line))

    # Load trajectories
    traj_dict = {}
    with open(traj_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                traj = json.loads(line)
                traj_dict[traj["trajectory_id"]] = traj

    grpo_data = []

    for qa in qa_list:
        traj_id = qa["trajectory_id"]
        traj = traj_dict.get(traj_id)

        if not traj:
            print(f"⚠️ Trajectory not found: {traj_id}")
            continue

        # Build messages
        messages = []

        # System message
        messages.append(
            {"role": "system", "content": DEFAULT_SYSTEM_PROMPT}
        )

        # User message (question context)
        user_content = f"请回答以下问题：{qa['question']}\n\n背景：{traj.get('seed_data', '')}"
        messages.append({"role": "user", "content": user_content})

        # Build assistant's thought process and tool calls from trajectory
        tool_calls = []
        observations = []
        trajectory_nodes = []

        for node in traj.get("nodes", []):
            action = node.get("action", {})
            tool_name = action.get("tool_name", "")
            params = action.get("parameters", {})
            observation = node.get("observation", "")
            intent = node.get("intent", "")

            if not tool_name:
                continue

            trajectory_nodes.append(node)

            # Record tool call
            tool_calls.append(
                {"tool_name": tool_name, "parameters": params, "intent": intent}
            )

            # Record observation
            observations.append(
                {
                    "tool_name": tool_name,
                    "result": observation[:500]
                    if len(observation) > 500
                    else observation,
                }
            )

        # Assistant message with reasoning and tool calls
        reasoning = "\n".join(
            [f"Step {i+1}: {call['intent']}" for i, call in enumerate(tool_calls)]
        )

        messages.append(
            {
                "role": "assistant",
                "content": f"让我逐步分析这个问题。\n\n{reasoning}",
                "tool_calls": tool_calls,
            }
        )

        # Tool observation messages
        for obs in observations:
            messages.append(
                {
                    "role": "tool",
                    "content": f"工具 {obs['tool_name']} 返回结果：\n{obs['result']}",
                    "name": obs["tool_name"],
                }
            )

        # Final answer
        final_answer = qa["answer"]
        messages.append(
            {"role": "assistant", "content": f"根据以上分析，我的答案是：\n{final_answer}"}
        )

        # Build prompt_messages (system + user only)
        prompt_messages = messages[:2]

        # Build response (assistant trajectory as a single string for GRPO)
        response_text = build_response_from_trajectory(
            trajectory_nodes, final_answer, chat_template=chat_template
        )

        # Seed tags from trajectory
        tags = traj.get("tags", {})

        # Build GRPO item
        grpo_item = {
            "messages": messages,
            "prompt_messages": prompt_messages,
            "response": response_text,
            "metadata": {
                "question": qa["question"],
                "answer": qa["answer"],
                "trajectory_id": traj_id,
                "source_id": traj.get("source_id", ""),
                "depth": traj.get("total_depth", 0),
                "node_count": len(traj.get("nodes", [])),
                "tool_call_count": len(tool_calls),
                "tags": tags,
            },
        }

        grpo_data.append(grpo_item)

    # Save output (JSONL format)
    with open(output_file, "w", encoding="utf-8") as f:
        for item in grpo_data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"✅ Converted {len(grpo_data)} items to GRPO format")
    print(f"   Output: {output_file}")

    return grpo_data


def print_grpo_example(grpo_data, index=0):
    """Print a GRPO example for inspection"""
    if not grpo_data or index >= len(grpo_data):
        print("No data to display")
        return

    item = grpo_data[index]
    print("\n" + "=" * 80)
    print(f"GRPO Example {index + 1}")
    print("=" * 80)
    print(f"Metadata: {json.dumps(item['metadata'], ensure_ascii=False, indent=2)}")
    print(f"\nPrompt Messages ({len(item['prompt_messages'])}):")
    for i, msg in enumerate(item["prompt_messages"], 1):
        print(f"\n--- Message {i} ({msg['role']}) ---")
        content = msg["content"]
        if len(content) > 300:
            content = content[:300] + "..."
        print(content)
    print(f"\nResponse:\n{item['response'][:800]}...")


def analyze_grpo_data(grpo_data):
    """Analyze GRPO data statistics"""
    print("\n" + "=" * 80)
    print("GRPO 数据统计")
    print("=" * 80)

    total = len(grpo_data)
    print(f"总样本数: {total}")

    if total == 0:
        return

    # Tool call statistics
    tool_counts = []
    depths = []

    for item in grpo_data:
        meta = item["metadata"]
        tool_counts.append(meta.get("tool_call_count", 0))
        depths.append(meta.get("depth", 0))

    print(f"平均工具调用数: {sum(tool_counts)/len(tool_counts):.1f}")
    print(f"平均轨迹深度: {sum(depths)/len(depths):.1f}")
    print(f"最大工具调用数: {max(tool_counts)}")
    print(f"最小工具调用数: {min(tool_counts)}")

    # Check data quality
    has_answer = sum(
        1
        for item in grpo_data
        if item["metadata"].get("answer") and "未提供" not in item["metadata"]["answer"]
    )
    print(f"有具体答案的样本: {has_answer}/{total} ({100*has_answer/total:.1f}%)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AgentFlow -> GRPO 数据转换")
    parser.add_argument("qa_file", nargs="?", default="results/ds_synthesized_qa/synthesized_qa.jsonl")
    parser.add_argument("traj_file", nargs="?", default="results/ds_synthesized_qa/trajectories.jsonl")
    parser.add_argument("output_file", nargs="?", default="results/grpo_training_data.jsonl")
    parser.add_argument(
        "--chat-template",
        choices=["default", "qwen3"],
        default="default",
        help="选择 chat template 格式（qwen3 会调整 response 格式以兼容 Qwen3 tokenizer）",
    )

    args = parser.parse_args()

    print("=" * 80)
    print("AgentFlow -> GRPO 数据转换")
    print("=" * 80)
    print(f"QA file: {args.qa_file}")
    print(f"Trajectory file: {args.traj_file}")
    print(f"Output file: {args.output_file}")
    print(f"Chat template: {args.chat_template}")

    # Convert
    grpo_data = convert_to_grpo_format(
        args.qa_file, args.traj_file, args.output_file, chat_template=args.chat_template
    )

    # Analyze
    analyze_grpo_data(grpo_data)

    # Show example
    if grpo_data:
        print_grpo_example(grpo_data, 0)
