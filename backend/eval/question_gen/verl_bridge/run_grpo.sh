#!/usr/bin/env bash
# GRPO | Qwen3-8B | SFT 暖启动(/root/sft_hf)| 2×A800 | MCP 对齐工具面 + 真 tushare
# 前置:tool_server 必须先起着(fria env,端口 8731):
#   PYTHONPATH=backend python -m eval.question_gen.verl_bridge.tool_server
# 可观测:SwanLab 云端(swanlab login 后),swanlab.cn 浏览器看。
# 用法:
#   smoke(2 步验证链路):           bash run_grpo.sh
#   全量(env 覆盖步数):  STEPS=40  bash run_grpo.sh
set -xeuo pipefail
REPO=/root/autodl-tmp/work/Financial-Research-Investment-Assistant
DATA=${DATA:-$REPO/backend/eval/question_gen/data/verl_grpo}  # 可 env 覆盖(如 verl_grpo_filtered)
MODEL=${MODEL_PATH:-/root/sft_hf}          # SFT 暖启动起点(非 base)
STEPS=${STEPS:-2}
EXP=${EXP:-grpo_sft_warmstart}
LR=${LR:-1e-6}                             # 难度筛选后可抬(advantage 救活了再放大步长)
NROLL=${NROLL:-8}                          # 每题 rollout 数(GRPO group size;增大→更易出组内分裂)
# 显存利用(8B+LoRA 在 80GB 卡):offload 关掉(参数/优化器小,放得下,省 CPU↔GPU 搬运),
# sglang KV cache 占比抬高 → rollout 更快、GPU 吃满。OOM 则调小 GPU_MEM / 开 OFFLOAD。
GPU_MEM=${GPU_MEM:-0.55}
OFFLOAD=${OFFLOAD:-False}

export PYTHONPATH=$REPO/backend${PYTHONPATH:+:$PYTHONPATH}
export PYTORCH_ALLOC_CONF=expandable_segments:True RAY_DEDUP_LOGS=0
export HF_HUB_OFFLINE=1
# SwanLab 云端(凭证已 swanlab login 存本地)
export SWANLAB_MODE=${SWANLAB_MODE:-cloud}
export CUDA_HOME=/usr/local/cuda-12.8
export PATH=$CUDA_HOME/bin:/root/autodl-tmp/envs/verl/bin:$PATH
# 本地 sglang rollout / tool_server 不走代理
export no_proxy=127.0.0.1,localhost NO_PROXY=127.0.0.1,localhost
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY || true
cd /root/autodl-tmp/verl

python3 -m verl.trainer.main_ppo \
  algorithm.adv_estimator=grpo \
  data.train_files=$DATA/train.parquet data.val_files=$DATA/val.parquet \
  data.train_batch_size=16 data.max_prompt_length=8192 data.max_response_length=4096 \
  data.return_raw_chat=True data.truncation=error algorithm.use_kl_in_reward=False \
  actor_rollout_ref.model.path="${MODEL}" \
  actor_rollout_ref.model.use_remove_padding=True \
  +actor_rollout_ref.model.override_config.attn_implementation=flash_attention_2 \
  actor_rollout_ref.model.lora_rank=32 actor_rollout_ref.model.lora_alpha=32 \
  'actor_rollout_ref.model.target_modules=[q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj]' \
  ++actor_rollout_ref.model.lora.merge=True \
  actor_rollout_ref.actor.optim.lr=${LR} actor_rollout_ref.actor.ppo_mini_batch_size=16 \
  actor_rollout_ref.actor.ppo_micro_batch_size_per_gpu=2 actor_rollout_ref.actor.use_kl_loss=True \
  actor_rollout_ref.actor.kl_loss_coef=0.001 actor_rollout_ref.actor.kl_loss_type=low_var_kl \
  actor_rollout_ref.actor.fsdp_config.param_offload=${OFFLOAD} actor_rollout_ref.actor.fsdp_config.optimizer_offload=${OFFLOAD} \
  actor_rollout_ref.rollout.log_prob_micro_batch_size_per_gpu=2 \
  actor_rollout_ref.ref.log_prob_micro_batch_size_per_gpu=2 actor_rollout_ref.ref.fsdp_config.param_offload=${OFFLOAD} \
  actor_rollout_ref.rollout.name=sglang actor_rollout_ref.rollout.mode=async \
  actor_rollout_ref.rollout.gpu_memory_utilization=${GPU_MEM} actor_rollout_ref.rollout.n=${NROLL} \
  actor_rollout_ref.rollout.free_cache_engine=True actor_rollout_ref.rollout.load_format=safetensors \
  actor_rollout_ref.rollout.layered_summon=True \
  actor_rollout_ref.rollout.multi_turn.enable=True \
  actor_rollout_ref.rollout.multi_turn.tool_config_path=$DATA/tool_config.yaml \
  actor_rollout_ref.rollout.multi_turn.max_tool_response_length=4096 \
  actor_rollout_ref.rollout.agent.default_agent_loop=tool_agent \
  +data.apply_chat_template_kwargs.enable_thinking=True \
  custom_reward_function.path=$REPO/backend/eval/question_gen/oracle_reward.py \
  custom_reward_function.name=compute_score reward_model.enable=False reward_model.reward_manager=naive \
  trainer.critic_warmup=0 trainer.logger='["console","swanlab"]' trainer.project_name=fin_grpo \
  trainer.experiment_name="${EXP}" trainer.n_gpus_per_node=2 trainer.nnodes=1 \
  trainer.save_freq=-1 trainer.test_freq=-1 trainer.val_before_train=False \
  trainer.total_training_steps=${STEPS} "$@"
