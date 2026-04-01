#!/usr/bin/env bash
# Launch GRPO training on 8x H20
# Actor: FSDP on 4 GPUs | Rollout: sglang on 4 GPUs (tp=4, ep=4)
set -euo pipefail

cd "$(dirname "$0")/../.."

CONFIG="configs/training/grpo_qwen3_30b_8xh20.yaml"

# Optional overrides via env
export SGLANG_TP_SIZE="${SGLANG_TP_SIZE:-4}"
export SGLANG_EP_SIZE="${SGLANG_EP_SIZE:-4}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0,1,2,3,4,5,6,7}"

echo "=============================================="
echo "Launching GRPO on 8x H20"
echo "Config: $CONFIG"
echo "CUDA_VISIBLE_DEVICES: $CUDA_VISIBLE_DEVICES"
echo "SGLANG TP=$SGLANG_TP_SIZE EP=$SGLANG_EP_SIZE"
echo "=============================================="

# Verify data exists
DATA_PATH="$(python -c "import yaml; print(yaml.safe_load(open('$CONFIG'))['training']['data_path'])")"
if [ ! -f "$DATA_PATH" ]; then
    echo "WARNING: Training data not found at $DATA_PATH"
    echo "Run ./training/scripts/prepare_data.sh first."
    exit 1
fi

# Optional: check sglang server
SGLANG_URL="$(python -c "import yaml; print(yaml.safe_load(open('$CONFIG'))['rollout'].get('sglang_url','http://127.0.0.1:30000'))")"
SGLANG_HOST="$(echo "$SGLANG_URL" | sed -E 's|http://([^:]+):.*|\1|')"
SGLANG_PORT="$(echo "$SGLANG_URL" | sed -E 's|http://[^:]+:(.*)|\1|')"

if ! curl -s "http://${SGLANG_HOST}:${SGLANG_PORT}/health" > /dev/null 2>&1; then
    echo "⚠️  SGLang server not detected at $SGLANG_URL"
    echo "Please start sglang with tp=$SGLANG_TP_SIZE ep=$SGLANG_EP_SIZE before launching training."
    echo "Example: python -m sglang.launch_server --model Qwen/Qwen3-30B-A3B --tp $SGLANG_TP_SIZE --ep $SGLANG_EP_SIZE"
fi

# Launch with ray if available
if command -v ray &> /dev/null; then
    echo "Detected ray. Starting training with Ray..."
    python training/verl/train_grpo.py --config "$CONFIG" "$@"
else
    echo "Ray not found. Launching standalone..."
    python training/verl/train_grpo.py --config "$CONFIG" "$@"
fi
