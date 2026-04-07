"""
训练效果评估脚本

用途：
  1. 对比 base model 和训练后 model 在 eval set 上的 reward 分布
  2. 分析 reward 各分量（format / content / tool_use）
  3. 输出到 wandb 和本地 JSON

使用方法：
  # 评估 checkpoint
  python training/eval/evaluate.py \
    --model results/checkpoints/step_100 \
    --data results/verl_eval_data.parquet \
    --base-model Qwen/Qwen2.5-7B-Instruct \
    --wandb-run finance-agent-grpo/qwen2-5-7b-lora-run1

  # 只看数字，不上传 wandb
  python training/eval/evaluate.py \
    --model results/checkpoints/step_100 \
    --data results/verl_eval_data.parquet \
    --no-wandb
"""

import argparse
import json
import os
from pathlib import Path
from typing import Optional

import pandas as pd


def load_eval_data(data_path: str) -> list[dict]:
    path = Path(data_path)
    if path.suffix == ".parquet":
        df = pd.read_parquet(path)
        return df.to_dict("records")
    else:
        records = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records


def generate_responses(model_path: str, prompts: list[str], max_new_tokens: int = 512) -> list[str]:
    """用 sglang 或 transformers 生成 response。优先使用 sglang。"""
    try:
        import sglang as sgl

        @sgl.function
        def generate(s, prompt):
            s += prompt
            s += sgl.gen("response", max_new_tokens=max_new_tokens, temperature=0.0)

        sgl.set_default_backend(sgl.RuntimeEndpoint("http://127.0.0.1:30000"))
        states = generate.run_batch([{"prompt": p} for p in prompts], progress_bar=True)
        return [s["response"] for s in states]

    except Exception:
        # fallback: transformers greedy decode
        from transformers import AutoModelForCausalLM, AutoTokenizer
        import torch

        print(f"sglang 不可用，使用 transformers 加载 {model_path}")
        tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(
            model_path, torch_dtype=torch.bfloat16, device_map="auto", trust_remote_code=True
        )
        responses = []
        for prompt in prompts:
            inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
            with torch.no_grad():
                out = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
            response = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
            responses.append(response)
        return responses


def compute_rewards(
    prompts: list[str],
    responses: list[str],
    metadata: list[dict],
    sandbox_url: str = "http://127.0.0.1:18890",
) -> list[dict]:
    """调用 AgentFlowReward 计算各分量。返回每条的 reward 明细。"""
    try:
        from training.reward import AgentFlowReward
        import asyncio
        import numpy as np

        reward_fn = AgentFlowReward(sandbox_server_url=sandbox_url)
        rewards = asyncio.run(reward_fn.compute_detailed(prompts, responses, metadata))
        return rewards
    except Exception as e:
        print(f"reward 计算失败（sandbox 可能未启动）: {e}")
        # 降级：只计算格式分
        results = []
        for r in responses:
            has_think = "<think>" in r and "</think>" in r
            results.append({"format": float(has_think), "content": 0.0, "total": float(has_think) * 0.3})
        return results


def print_summary(label: str, reward_details: list[dict]) -> dict:
    import statistics

    totals = [d["total"] for d in reward_details]
    formats = [d.get("format", 0.0) for d in reward_details]
    contents = [d.get("content", 0.0) for d in reward_details]

    summary = {
        "label": label,
        "n": len(totals),
        "reward_mean": statistics.mean(totals),
        "reward_std": statistics.stdev(totals) if len(totals) > 1 else 0.0,
        "reward_min": min(totals),
        "reward_max": max(totals),
        "format_mean": statistics.mean(formats),
        "content_mean": statistics.mean(contents),
    }

    print(f"\n{'='*50}")
    print(f"  {label}")
    print(f"{'='*50}")
    print(f"  样本数:        {summary['n']}")
    print(f"  reward 均值:   {summary['reward_mean']:.4f} ± {summary['reward_std']:.4f}")
    print(f"  reward 范围:   [{summary['reward_min']:.4f}, {summary['reward_max']:.4f}]")
    print(f"  format 分均值: {summary['format_mean']:.4f}")
    print(f"  content 分均值:{summary['content_mean']:.4f}")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="训练后的 checkpoint 路径")
    parser.add_argument("--data", required=True, help="eval 数据路径（parquet 或 jsonl）")
    parser.add_argument("--base-model", default=None, help="base model 路径，用于对比（可选）")
    parser.add_argument("--max-samples", type=int, default=100, help="最多评估多少条")
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument("--sandbox-url", default="http://127.0.0.1:18890")
    parser.add_argument("--wandb-run", default=None, help="wandb run path，格式: project/run_id")
    parser.add_argument("--no-wandb", action="store_true")
    parser.add_argument("--output", default="results/eval_result.json")
    args = parser.parse_args()

    # 加载数据
    records = load_eval_data(args.data)[: args.max_samples]
    prompts = [r["prompt"] for r in records]
    metadata = [r.get("metadata", {}) for r in records]
    print(f"加载 {len(records)} 条 eval 数据")

    results = {}

    # 评估训练后模型
    print(f"\n生成 responses（训练后模型: {args.model}）...")
    trained_responses = generate_responses(args.model, prompts, args.max_new_tokens)
    trained_rewards = compute_rewards(prompts, trained_responses, metadata, args.sandbox_url)
    results["trained"] = print_summary("训练后模型", trained_rewards)

    # 对比 base model（可选）
    if args.base_model:
        print(f"\n生成 responses（base model: {args.base_model}）...")
        base_responses = generate_responses(args.base_model, prompts, args.max_new_tokens)
        base_rewards = compute_rewards(prompts, base_responses, metadata, args.sandbox_url)
        results["base"] = print_summary("Base Model", base_rewards)

        improvement = results["trained"]["reward_mean"] - results["base"]["reward_mean"]
        print(f"\n  reward 提升:   {improvement:+.4f}")
        results["improvement"] = improvement

    # 保存结果
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存到 {args.output}")

    # 上传 wandb
    if not args.no_wandb and args.wandb_run:
        try:
            import wandb

            project, run_id = args.wandb_run.rsplit("/", 1)
            run = wandb.init(project=project, id=run_id, resume="allow")
            log_data = {f"eval/{k}": v for k, v in results.get("trained", {}).items() if isinstance(v, float)}
            if "base" in results:
                log_data["eval/improvement"] = results["improvement"]
            run.log(log_data)
            run.finish()
            print("wandb 上传完成")
        except Exception as e:
            print(f"wandb 上传失败: {e}")


if __name__ == "__main__":
    main()
