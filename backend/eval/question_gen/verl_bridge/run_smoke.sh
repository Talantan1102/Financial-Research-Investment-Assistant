#!/usr/bin/env bash
set -xeuo pipefail
REPO=/root/autodl-tmp/work/Financial-Research-Investment-Assistant
export PYTHONPATH=$REPO/backend${PYTHONPATH:+:$PYTHONPATH}
export HF_ENDPOINT=https://hf-mirror.com PYTORCH_ALLOC_CONF=expandable_segments:True RAY_DEDUP_LOGS=0
cd /root/autodl-tmp/verl
python3 -m verl.trainer.main_ppo \
  algorithm.adv_estimator=grpo \
  data.train_files=$REPO/backend/eval/question_gen/data/verl_smoke/train.parquet data.val_files=$REPO/backend/eval/question_gen/data/verl_smoke/val.parquet \
  data.train_batch_size=8 data.max_prompt_length=4096 data.max_response_length=2048 \
  data.return_raw_chat=True data.truncation=error algorithm.use_kl_in_reward=False \
  actor_rollout_ref.model.path=/root/autodl-tmp/models/Qwen3-8B \
  actor_rollout_ref.model.use_remove_padding=False \
  +actor_rollout_ref.model.override_config.attn_implementation=sdpa \
  actor_rollout_ref.model.lora_rank=32 actor_rollout_ref.model.lora_alpha=32 \
  'actor_rollout_ref.model.target_modules=[q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj]' \
  ++actor_rollout_ref.model.lora.merge=True \
  actor_rollout_ref.actor.optim.lr=1e-5 actor_rollout_ref.actor.ppo_mini_batch_size=8 \
  actor_rollout_ref.actor.ppo_micro_batch_size_per_gpu=2 actor_rollout_ref.actor.use_kl_loss=True \
  actor_rollout_ref.actor.kl_loss_coef=0.001 actor_rollout_ref.actor.kl_loss_type=low_var_kl \
  actor_rollout_ref.rollout.log_prob_micro_batch_size_per_gpu=2 \
  actor_rollout_ref.ref.log_prob_micro_batch_size_per_gpu=2 actor_rollout_ref.ref.fsdp_config.param_offload=True \
  actor_rollout_ref.rollout.name=sglang actor_rollout_ref.rollout.mode=async \
  actor_rollout_ref.rollout.gpu_memory_utilization=0.4 actor_rollout_ref.rollout.n=8 \
  actor_rollout_ref.rollout.free_cache_engine=True actor_rollout_ref.rollout.load_format=safetensors \
  actor_rollout_ref.rollout.layered_summon=True \
  actor_rollout_ref.rollout.multi_turn.enable=True \
  actor_rollout_ref.rollout.multi_turn.tool_config_path=$REPO/backend/eval/question_gen/data/verl_smoke/tool_config.yaml \
  actor_rollout_ref.rollout.multi_turn.max_tool_response_length=4096 \
  actor_rollout_ref.rollout.agent.default_agent_loop=tool_agent \
  +data.apply_chat_template_kwargs.enable_thinking=False \
  custom_reward_function.path=$REPO/backend/eval/question_gen/oracle_reward.py \
  custom_reward_function.name=compute_score reward_model.enable=False reward_model.reward_manager=naive \
  trainer.critic_warmup=0 trainer.logger='["console"]' trainer.project_name=fin_d3 \
  trainer.experiment_name=d3_tool_smoke trainer.n_gpus_per_node=2 trainer.nnodes=1 \
  trainer.save_freq=-1 trainer.test_freq=-1 trainer.val_before_train=False trainer.total_training_steps=2 "$@"
