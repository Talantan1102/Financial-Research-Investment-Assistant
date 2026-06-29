#!/usr/bin/env bash
# SFT | qwen3-8b LoRA | FSDP | 2×A800 —— D4 数据暖启(GRPO 前)
# 手册: docs/superpowers/plans/2026-06-27-sft-execution-manual.md
#
# 用法:
#   先建数据: PYTHONPATH=backend python -m eval.question_gen.build_sft_parquet
#   配置自检(2 步,~5min 抓配置错): TOTAL_STEPS=2 bash run_sft.sh 2 /tmp/sft_ckpt
#   全量(2 epoch): bash run_sft.sh 2 /root/autodl-tmp/sft_ckpt
set -xeuo pipefail

NPROC=${1:-2}
SAVE=${2:-/root/autodl-tmp/sft_ckpt}
shift 2 || true

REPO=/root/autodl-tmp/work/Financial-Research-Investment-Assistant
DATA=$REPO/backend/eval/question_gen/data/sft_parquet
MODEL=${MODEL_PATH:-/root/autodl-tmp/models/Qwen3-8B}

# 超参(手册 §4/§11;可 env 覆盖)
LR=${LR:-1e-4}
EPOCHS=${EPOCHS:-2}
LORA_RANK=${LORA_RANK:-32}
LORA_ALPHA=${LORA_ALPHA:-32}        # 手册:alpha=rank
MAXLEN=${MAXLEN:-32768}             # 全留,不截(实测 max=24501)
TOK_PER_GPU=${TOK_PER_GPU:-32768}   # dynamic bsz 每卡 token 预算;SP=1 下必须 ≥ 最长序列(实测 24501)
TOTAL_STEPS=${TOTAL_STEPS:-}        # 设了就限步(配置自检用)

export PYTHONPATH=$REPO/backend${PYTHONPATH:+:$PYTHONPATH}
export PYTORCH_ALLOC_CONF=expandable_segments:True
# SwanLab 监控(免代理 local 离线模式;看板 `swanlab watch $SWANLAB_LOG_DIR`)
# 切云端: SWANLAB_MODE=cloud SWANLAB_API_KEY=xxx
export SWANLAB_MODE=${SWANLAB_MODE:-local}
export SWANLAB_LOG_DIR=${SWANLAB_LOG_DIR:-/root/swanlog}
cd /root/autodl-tmp/verl

extra=()
[ -n "$TOTAL_STEPS" ] && extra+=("trainer.total_training_steps=${TOTAL_STEPS}")

torchrun --standalone --nnodes=1 --nproc_per_node=${NPROC} \
  -m verl.trainer.sft_trainer \
  data.train_files=$DATA/train.parquet \
  data.val_files=$DATA/val.parquet \
  data.messages_key=messages \
  data.custom_cls.path=$REPO/backend/eval/question_gen/verl_bridge/whole_render_sft_dataset.py \
  data.custom_cls.name=WholeRenderMultiTurnSFTDataset \
  data.max_length=${MAXLEN} \
  data.truncation=error \
  data.use_dynamic_bsz=True \
  data.max_token_len_per_gpu=${TOK_PER_GPU} \
  data.pad_mode=no_padding \
  optim.lr=${LR} \
  optim.lr_scheduler_type=cosine \
  optim.lr_warmup_steps_ratio=0.05 \
  optim.weight_decay=0.01 \
  engine=fsdp \
  engine.ulysses_sequence_parallel_size=1 \
  engine.optimizer_offload=True \
  engine.param_offload=True \
  model.path="${MODEL}" \
  model.trust_remote_code=True \
  model.use_remove_padding=True \
  +model.override_config.attn_implementation=flash_attention_2 \
  model.enable_gradient_checkpointing=True \
  model.lora_rank=${LORA_RANK} \
  model.lora_alpha=${LORA_ALPHA} \
  model.target_modules=all-linear \
  trainer.default_local_dir="${SAVE}" \
  'checkpoint.save_contents=[model]' \
  trainer.project_name=fin_sft \
  trainer.experiment_name=d4_sft_qwen3_8b \
  trainer.logger="${SFT_LOGGER:-[\"console\"]}" \
  trainer.total_epochs=${EPOCHS} \
  trainer.save_freq=-1 \
  trainer.test_freq=20 \
  "${extra[@]}" "$@"
