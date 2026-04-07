#!/usr/bin/env bash
# GRPO + LoRA 训练（基于 verl-tool）
#
# 硬件要求：2x A100 40GB（或同等显存）
#   GPU 0: Actor 训练（FSDP）
#   GPU 1: vLLM rollout 推理
#
# 前置条件：
#   1. pip install verl-tool
#   2. wandb login
#   3. Sandbox + tool server 已启动:
#      ./start_sandbox_server.sh --config configs/sandbox-server/finance_research_config.json
#      bash training/scripts/start_tool_server.sh
#   4. 训练数据已准备:
#      python training/data/build_parquet.py --input results/grpo_training_data.jsonl --output results/train.parquet
#
# 用法：
#   bash training/scripts/train_grpo_lora.sh

set -euo pipefail

cd "$(dirname "$0")/../.."

# ── 配置 ────────────────────────────────────────────────────────
MODEL="${MODEL:-Qwen/Qwen2.5-7B-Instruct}"
TRAIN_DATA="${TRAIN_DATA:-results/train.parquet}"
EVAL_DATA="${EVAL_DATA:-results/eval.parquet}"
TOOL_SERVER_URL="${TOOL_SERVER_URL:-http://127.0.0.1:5005}"

# LoRA
LORA_RANK="${LORA_RANK:-16}"

# Rollout
ROLLOUT_N="${ROLLOUT_N:-4}"          # GRPO group size
MAX_TURNS="${MAX_TURNS:-5}"          # 最多 5 轮工具调用
MAX_PROMPT_LEN="${MAX_PROMPT_LEN:-1024}"
MAX_RESPONSE_LEN="${MAX_RESPONSE_LEN:-1024}"
MAX_OBS_LEN="${MAX_OBS_LEN:-512}"    # 工具返回截断长度

# Training
LR="${LR:-1e-5}"
BATCH_SIZE="${BATCH_SIZE:-32}"
MINI_BATCH="${MINI_BATCH:-8}"
MICRO_BATCH="${MICRO_BATCH:-2}"
TOTAL_EPOCHS="${TOTAL_EPOCHS:-2}"
SAVE_FREQ="${SAVE_FREQ:-50}"
TEST_FREQ="${TEST_FREQ:-20}"
KL_COEF="${KL_COEF:-0.001}"

# wandb
WANDB_PROJECT="${WANDB_PROJECT:-finance-agent-grpo}"
WANDB_RUN="${WANDB_RUN:-qwen2.5-7b-lora-$(date +%m%d-%H%M)}"

# ── 前置检查 ────────────────────────────────────────────────────
echo "=============================================="
echo "GRPO + LoRA Training (verl-tool)"
echo "  Model:      ${MODEL}"
echo "  LoRA rank:  ${LORA_RANK}"
echo "  Data:       ${TRAIN_DATA}"
echo "  Tool:       ${TOOL_SERVER_URL}"
echo "  wandb:      ${WANDB_PROJECT}/${WANDB_RUN}"
echo "=============================================="

# 检查数据
if [ ! -f "$TRAIN_DATA" ]; then
    echo "训练数据不存在: ${TRAIN_DATA}"
    echo "请先运行: python training/data/build_parquet.py --input results/grpo_training_data.jsonl --output results/train.parquet"
    exit 1
fi

# 检查 tool server
if ! curl -s "${TOOL_SERVER_URL}/health" > /dev/null 2>&1; then
    echo "Tool server 未启动: ${TOOL_SERVER_URL}"
    echo "请先运行: bash training/scripts/start_tool_server.sh"
    exit 1
fi

# 检查 wandb
if ! python -c "import wandb; assert wandb.api.api_key" 2>/dev/null; then
    echo "请先登录 wandb: wandb login"
    exit 1
fi

# ── 注册自定义 reward manager ──────────────────────────────────
# 将项目的 reward_manager 加入 Python path，verl-tool 会自动发现
export PYTHONPATH="${PWD}/training:${PYTHONPATH:-}"

# ── 启动训练 ────────────────────────────────────────────────────
python -m verl_tool.trainer.main_ppo \
    algorithm.adv_estimator=grpo \
    algorithm.kl_ctrl.type=fixed \
    algorithm.kl_ctrl.kl_coef="${KL_COEF}" \
    \
    data.train_files="[\"${TRAIN_DATA}\"]" \
    data.val_files="[\"${EVAL_DATA}\"]" \
    data.train_batch_size="${BATCH_SIZE}" \
    data.max_prompt_length="${MAX_PROMPT_LEN}" \
    data.max_response_length="${MAX_RESPONSE_LEN}" \
    \
    reward_model.reward_manager=simple_finance \
    \
    actor_rollout_ref.model.path="${MODEL}" \
    actor_rollout_ref.actor.optim.lr="${LR}" \
    actor_rollout_ref.actor.strategy=fsdp \
    actor_rollout_ref.actor.ppo_mini_batch_size="${MINI_BATCH}" \
    actor_rollout_ref.actor.ppo_micro_batch_size_per_gpu="${MICRO_BATCH}" \
    actor_rollout_ref.actor.lora.enabled=true \
    actor_rollout_ref.actor.lora.r="${LORA_RANK}" \
    actor_rollout_ref.actor.lora.lora_alpha=32 \
    actor_rollout_ref.actor.lora.target_modules="[q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj]" \
    \
    actor_rollout_ref.rollout.name=vllm \
    actor_rollout_ref.rollout.n="${ROLLOUT_N}" \
    actor_rollout_ref.rollout.gpu_memory_utilization=0.5 \
    \
    actor_rollout_ref.agent.enable_agent=true \
    actor_rollout_ref.agent.tool_server_url="${TOOL_SERVER_URL}" \
    actor_rollout_ref.agent.max_turns="${MAX_TURNS}" \
    actor_rollout_ref.agent.max_prompt_length="${MAX_PROMPT_LEN}" \
    actor_rollout_ref.agent.max_response_length="${MAX_RESPONSE_LEN}" \
    actor_rollout_ref.agent.max_obs_length="${MAX_OBS_LEN}" \
    actor_rollout_ref.agent.action_stop_tokens="[\"</tool_call>\",\"</answer>\"]" \
    actor_rollout_ref.agent.mask_observations=true \
    \
    trainer.total_epochs="${TOTAL_EPOCHS}" \
    trainer.save_freq="${SAVE_FREQ}" \
    trainer.test_freq="${TEST_FREQ}" \
    trainer.project_name="${WANDB_PROJECT}" \
    trainer.experiment_name="${WANDB_RUN}" \
    trainer.logger="[console,wandb]" \
    trainer.default_local_dir=results/checkpoints \
    "$@"
