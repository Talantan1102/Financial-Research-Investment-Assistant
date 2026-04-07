#!/usr/bin/env bash
# GRPO + LoRA 训练，2x A100 40GB
# GPU 0: Actor (FSDP)   GPU 1: sglang rollout
set -euo pipefail

cd "$(dirname "$0")/../.."

CONFIG="configs/training/grpo_qwen2_5_7b_lora_2gpu.yaml"

# ── 1. 检查 wandb 登录 ──────────────────────────────────────────────
if ! python -c "import wandb; assert wandb.api.api_key" 2>/dev/null; then
    echo "请先登录 wandb: wandb login"
    exit 1
fi

# ── 2. 检查数据 ────────────────────────────────────────────────────
if [ ! -f "results/verl_training_data.parquet" ]; then
    echo "训练数据不存在，先运行数据准备:"
    echo "  python training/verl/data/build_verl_dataset.py --to-parquet ..."
    exit 1
fi

# ── 3. 检查 sglang 服务（GPU 1）────────────────────────────────────
if ! curl -s http://127.0.0.1:30000/health > /dev/null 2>&1; then
    echo "sglang 未启动，请在另一个终端执行:"
    echo ""
    echo "  CUDA_VISIBLE_DEVICES=1 python -m sglang.launch_server \\"
    echo "    --model Qwen/Qwen2.5-7B-Instruct \\"
    echo "    --port 30000 --tp 1"
    echo ""
    echo "等待 sglang 启动后再运行此脚本。"
    exit 1
fi

echo "=============================================="
echo "GRPO + LoRA 训练 (2x A100)"
echo "Config: $CONFIG"
echo "wandb project: finance-agent-grpo"
echo "=============================================="

# ── 4. 启动训练（GPU 0 做 actor）──────────────────────────────────
CUDA_VISIBLE_DEVICES=0 python -m verl.trainer.main_ppo \
    --config "$CONFIG" \
    "$@"
