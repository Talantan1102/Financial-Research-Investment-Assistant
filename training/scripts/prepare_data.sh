#!/usr/bin/env bash
# One-click data preparation: synthesis → convert → build verl dataset
set -euo pipefail

# Default paths
SYNTHESIS_CONFIG="${1:-configs/synthesis/temp_grpo_20_seeds.json}"
QA_OUTPUT_DIR="results/ds_synthesized_qa"
GRPO_OUTPUT="results/grpo_training_data.jsonl"
VERL_OUTPUT="results/verl_training_data.jsonl"
MODEL_NAME="${MODEL_NAME:-Qwen/Qwen3-30B-A3B}"

echo "=============================================="
echo "AgentFlow GRPO Data Preparation Pipeline"
echo "=============================================="
echo "Synthesis config: $SYNTHESIS_CONFIG"
echo "Model name: $MODEL_NAME"

# Step 1: Run synthesis pipeline
echo ""
echo "[Step 1/3] Running synthesis pipeline..."
python synthesis/pipeline.py --config "$SYNTHESIS_CONFIG"

# Step 2: Convert to GRPO format
echo ""
echo "[Step 2/3] Converting to GRPO format..."
QA_FILE="$QA_OUTPUT_DIR/synthesized_qa.jsonl"
TRAJ_FILE="$QA_OUTPUT_DIR/trajectories.jsonl"

if [ ! -f "$QA_FILE" ]; then
    echo "ERROR: QA file not found: $QA_FILE"
    exit 1
fi
if [ ! -f "$TRAJ_FILE" ]; then
    echo "ERROR: Trajectory file not found: $TRAJ_FILE"
    exit 1
fi

python scripts/pipeline/convert_to_grpo.py \
    "$QA_FILE" \
    "$TRAJ_FILE" \
    "$GRPO_OUTPUT" \
    --chat-template qwen3

# Step 3: Build verl dataset
echo ""
echo "[Step 3/3] Building verl dataset..."
python training/verl/data/build_verl_dataset.py \
    --input "$GRPO_OUTPUT" \
    --output "$VERL_OUTPUT" \
    --model_name "$MODEL_NAME"

echo ""
echo "=============================================="
echo "Data preparation complete!"
echo "  GRPO data:  $GRPO_OUTPUT"
echo "  verl data:  $VERL_OUTPUT"
echo "=============================================="
