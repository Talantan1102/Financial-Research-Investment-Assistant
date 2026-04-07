"""
构建 verl-tool 训练数据（parquet 格式）。

输入：GRPO training JSONL（from convert_to_grpo.py）
输出：verl-tool 所需的 parquet 文件，含 prompt / reward_model / extra_info

verl-tool 要求每条数据包含：
  - prompt: list[dict]  # chat messages (system + user)
  - reward_model: dict   # {"style": "rule", "ground_truth": "..."}
  - extra_info: dict      # MCP 服务器信息、验证配置等

Usage:
    python training/data/build_parquet.py \
        --input results/grpo_training_data.jsonl \
        --output results/train.parquet \
        --eval-split 0.1
"""

import argparse
import json
import random
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd


SYSTEM_PROMPT = """你是一个金融研投助手。你可以使用工具来获取市场数据、财务分析等信息。

使用工具时，请用以下格式：
<tool_call>
{"name": "tool_name", "arguments": {"key": "value"}}
</tool_call>

工具返回结果后，继续分析。最终给出结论时，用以下格式：
<answer>
你的最终回答
</answer>

要求：
1. 先思考需要哪些信息
2. 调用合适的工具获取数据
3. 基于数据给出有依据的结论
4. 避免冗余的工具调用"""


def load_jsonl(path: str) -> List[Dict[str, Any]]:
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def convert_to_verl_tool_format(records: List[Dict]) -> List[Dict]:
    """将 GRPO JSONL 转为 verl-tool parquet 格式。"""
    items = []
    for rec in records:
        # 提取 user query
        prompt_messages = rec.get("prompt_messages", [])
        if not prompt_messages:
            messages = rec.get("messages", [])
            prompt_messages = [m for m in messages if m.get("role") in ("system", "user")]

        user_content = ""
        for m in prompt_messages:
            if m.get("role") == "user":
                user_content = m.get("content", "")
                break

        if not user_content:
            continue

        # 构建 prompt（system + user）
        prompt = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        # 提取 metadata
        metadata = rec.get("metadata", {})
        tags = metadata.get("tags", {})

        # ground truth（如果有）
        ground_truth = metadata.get("ground_truth", tags.get("expected_answer", ""))

        # 构建 reward_model 字段
        reward_model = {
            "style": "rule",
            "ground_truth": str(ground_truth) if ground_truth else "",
        }

        # extra_info：MCP 服务器配置
        extra_info = {
            "mcp_servers": [{"name": "unified_finance"}],
            "use_specified_server": True,
            "tags": tags,
        }

        items.append({
            "prompt": json.dumps(prompt, ensure_ascii=False),
            "reward_model": json.dumps(reward_model, ensure_ascii=False),
            "extra_info": json.dumps(extra_info, ensure_ascii=False),
        })

    return items


def main():
    parser = argparse.ArgumentParser(description="Build verl-tool training parquet")
    parser.add_argument("--input", required=True, help="GRPO training JSONL")
    parser.add_argument("--output", required=True, help="Output parquet path")
    parser.add_argument("--eval-split", type=float, default=0.1, help="Eval set ratio")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    records = load_jsonl(args.input)
    print(f"Loaded {len(records)} records from {args.input}")

    items = convert_to_verl_tool_format(records)
    print(f"Converted {len(items)} valid items")

    if not items:
        print("No valid items. Check input format.")
        return

    # Shuffle and split
    random.seed(args.seed)
    random.shuffle(items)

    if args.eval_split > 0:
        split = int(len(items) * (1 - args.eval_split))
        train_items, eval_items = items[:split], items[split:]
    else:
        train_items, eval_items = items, []

    # Save
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    df_train = pd.DataFrame(train_items)
    df_train.to_parquet(str(output), index=False)
    print(f"Train: {len(train_items)} items -> {output}")

    if eval_items:
        eval_path = str(output).replace("train", "eval")
        df_eval = pd.DataFrame(eval_items)
        df_eval.to_parquet(eval_path, index=False)
        print(f"Eval:  {len(eval_items)} items -> {eval_path}")


if __name__ == "__main__":
    main()
