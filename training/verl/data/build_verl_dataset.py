"""
Build verl-compatible dataset from GRPO training data.

Reads the JSONL output from convert_to_grpo.py and uses the Qwen3 tokenizer
to produce `prompt` (string with generation prompt) and `response` fields.

Usage:
    python build_verl_dataset.py \
        --input results/grpo_training_data.jsonl \
        --output results/verl_training_data.jsonl \
        --model_name Qwen/Qwen3-30B-A3B
"""

import json
import argparse
from pathlib import Path
from typing import Dict, Any, List


def load_grpo_data(input_path: str) -> List[Dict[str, Any]]:
    data = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                data.append(json.loads(line))
    return data


def build_verl_items(
    grpo_data: List[Dict[str, Any]],
    tokenizer,
    add_generation_prompt: bool = True,
) -> List[Dict[str, Any]]:
    """
    Build verl dataset items from GRPO data.

    Each item has:
        - prompt: chat-templated string up to the user turn (with generation prompt)
        - response: the reference assistant response string
        - metadata: passed through for reward_fn usage
    """
    verl_items = []
    for item in grpo_data:
        prompt_messages = item.get("prompt_messages", item["messages"][:2])
        response_text = item.get("response", "")
        metadata = item.get("metadata", {})

        # Apply chat template to get the prompt string
        if tokenizer is not None:
            prompt = tokenizer.apply_chat_template(
                prompt_messages,
                tokenize=False,
                add_generation_prompt=add_generation_prompt,
            )
        else:
            # Fallback when tokenizer not available
            prompt = "\n".join(
                [
                    f"{msg.get('role', 'user')}: {msg.get('content', '')}"
                    for msg in prompt_messages
                ]
            )
            if add_generation_prompt:
                prompt += "\nassistant:"

        verl_items.append(
            {
                "prompt": prompt,
                "response": response_text,
                "metadata": metadata,
            }
        )

    return verl_items


def save_verl_data(verl_items: List[Dict[str, Any]], output_path: str, as_parquet: bool = False) -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    if as_parquet:
        import pandas as pd
        df = pd.DataFrame(verl_items)
        df.to_parquet(output_path, index=False)
    else:
        with open(output_path, "w", encoding="utf-8") as f:
            for item in verl_items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Build verl dataset from GRPO data")
    parser.add_argument(
        "--input",
        required=True,
        help="Path to GRPO training data JSONL",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to output verl dataset JSONL",
    )
    parser.add_argument(
        "--model_name",
        default="Qwen/Qwen3-30B-A3B",
        help="Tokenizer model name or path",
    )
    parser.add_argument(
        "--no-tokenizer",
        action="store_true",
        help="Skip loading transformer tokenizer (for environments without torch/transformers)",
    )
    parser.add_argument(
        "--add-generation-prompt",
        action="store_true",
        default=True,
        help="Add generation prompt to the end of prompt string",
    )
    parser.add_argument(
        "--to-parquet",
        action="store_true",
        help="输出 parquet 格式（verl 要求），默认输出 jsonl",
    )
    parser.add_argument(
        "--eval-split",
        type=float,
        default=0.1,
        help="切出多少比例作为 eval set（默认 0.1，0 表示不切）",
    )

    args = parser.parse_args()

    tokenizer = None
    if not args.no_tokenizer:
        try:
            from transformers import AutoTokenizer

            print(f"Loading tokenizer: {args.model_name}")
            tokenizer = AutoTokenizer.from_pretrained(
                args.model_name, trust_remote_code=True
            )
        except Exception as e:
            print(f"⚠️ Failed to load tokenizer: {e}")
            print("Falling back to plain-text prompt construction.")
            tokenizer = None

    print(f"Loading GRPO data from {args.input}")
    grpo_data = load_grpo_data(args.input)
    print(f"Loaded {len(grpo_data)} samples")

    if grpo_data and tokenizer is not None:
        # Quick sanity check
        sample_prompt = tokenizer.apply_chat_template(
            grpo_data[0]["prompt_messages"],
            tokenize=False,
            add_generation_prompt=args.add_generation_prompt,
        )
        print("\n--- Sample prompt (first 300 chars) ---")
        print(sample_prompt[:300])
        print("--- Sample response (first 300 chars) ---")
        print(grpo_data[0].get("response", "")[:300])

    verl_items = build_verl_items(
        grpo_data,
        tokenizer,
        add_generation_prompt=args.add_generation_prompt,
    )

    # 切分 train / eval
    if args.eval_split > 0:
        import random
        random.shuffle(verl_items)
        split = int(len(verl_items) * (1 - args.eval_split))
        train_items, eval_items = verl_items[:split], verl_items[split:]
    else:
        train_items, eval_items = verl_items, []

    ext = ".parquet" if args.to_parquet else ".jsonl"
    train_out = args.output if args.output.endswith(ext) else args.output.replace(".jsonl", ext).replace(".parquet", ext)
    save_verl_data(train_items, train_out, as_parquet=args.to_parquet)
    print(f"\n✅ Train: {len(train_items)} items → {train_out}")

    if eval_items:
        eval_out = train_out.replace("training_data", "eval_data")
        save_verl_data(eval_items, eval_out, as_parquet=args.to_parquet)
        print(f"✅ Eval:  {len(eval_items)} items → {eval_out}")


if __name__ == "__main__":
    main()
