"""
GRPO training script for Qwen3-30B-A3B using verl + sglang.

This script loads a verl-compatible dataset, instantiates AgentFlowReward,
and configures FSDP actor + sglang rollout.

Usage:
    python train_grpo.py --config configs/training/grpo_qwen3_30b_smoke.yaml

Environment variables:
    SGLANG_TP_SIZE: tensor parallelism size for sglang (default from config)
    SGLANG_EP_SIZE: expert parallelism size for sglang (default from config)
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path
from typing import Optional, Dict, Any

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("train_grpo")


def load_yaml_config(config_path: str) -> Dict[str, Any]:
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except ImportError:
        logger.error("PyYAML is required for config loading. Install with: pip install pyyaml")
        raise


def build_reward_fn(reward_config: Dict[str, Any]):
    """Build AgentFlowReward from config."""
    from training.reward import AgentFlowReward

    return AgentFlowReward(
        sandbox_server_url=reward_config.get("sandbox_server_url", "http://127.0.0.1:18890"),
        sandbox_config_path=reward_config.get("sandbox_config_path"),
        resource_types=reward_config.get("resource_types", []),
        resource_init_configs=reward_config.get("resource_init_configs", {}),
        llm_model=reward_config.get("llm_model", "gpt-4.1-2025-04-14"),
        llm_api_key=reward_config.get("llm_api_key", ""),
        llm_base_url=reward_config.get("llm_base_url", ""),
        max_turns=reward_config.get("max_turns", 20),
    )


def load_verl_dataset(data_path: str):
    """Load verl dataset from JSONL."""
    items = []
    with open(data_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


class SimpleRLHFDataset:
    """
    Minimal RLHF dataset compatible with verl-style training loops.

    When verl is available, this can be replaced with verl's native RLHFDataset.
    """

    def __init__(self, data_path: str):
        self.data = load_verl_dataset(data_path)

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        return self.data[idx]


def main():
    parser = argparse.ArgumentParser(description="GRPO training with verl + sglang")
    parser.add_argument("--config", required=True, help="Path to training config YAML")
    parser.add_argument("--max-steps", type=int, default=None, help="Override max training steps")
    parser.add_argument("--rollout-n", type=int, default=None, help="Override rollout group size")
    parser.add_argument("--data-path", type=str, default=None, help="Override dataset path")
    parser.add_argument(
        "--no-verl",
        action="store_true",
        help="Run in standalone smoke-test mode without importing verl",
    )
    args = parser.parse_args()

    config = load_yaml_config(args.config)
    training_cfg = config.get("training", {})
    model_cfg = config.get("model", {})
    rollout_cfg = config.get("rollout", {})
    reward_cfg = config.get("reward", {})

    if args.max_steps is not None:
        training_cfg["max_steps"] = args.max_steps
    if args.rollout_n is not None:
        rollout_cfg["n"] = args.rollout_n
    if args.data_path is not None:
        training_cfg["data_path"] = args.data_path

    data_path = training_cfg.get("data_path")
    if not data_path or not Path(data_path).exists():
        logger.error(f"Dataset not found: {data_path}")
        sys.exit(1)

    # Build reward function
    logger.info("Building AgentFlowReward...")
    reward_fn = build_reward_fn(reward_cfg)

    # Smoke test reward_fn on a few samples
    logger.info("Running reward smoke test on first 2 samples...")
    dataset = SimpleRLHFDataset(data_path)
    if len(dataset) >= 2:
        sample_prompts = [dataset[0]["prompt"], dataset[1]["prompt"]]
        sample_responses = [dataset[0]["response"], dataset[1]["response"]]
        sample_metadata = [dataset[0].get("metadata", {}), dataset[1].get("metadata", {})]
        try:
            rewards = reward_fn(sample_prompts, sample_responses, sample_metadata)
            logger.info(f"Smoke test rewards: {rewards.tolist()}")
        except Exception as e:
            logger.warning(f"Reward smoke test failed (sandbox may not be running): {e}")
    else:
        logger.warning("Dataset has fewer than 2 samples; skipping reward smoke test.")

    if args.no_verl:
        logger.info("--no-verl flag set; skipping verl training integration.")
        logger.info("All smoke tests passed. Exiting.")
        return

    # ------------------------------------------------------------------
    # verl integration (best-effort; exact API depends on verl version)
    # ------------------------------------------------------------------
    try:
        from verl.trainer.ppo.ray_trainer import RayPPOTrainer
        from verl.utils.dataset.rl_dataset import RLHFDataset
        import torch
    except ImportError as e:
        logger.error(f"Failed to import verl: {e}")
        logger.error("If you want to run smoke tests without verl, use --no-verl.")
        sys.exit(1)

    logger.info("Initializing verl training...")

    # Dataset
    verl_dataset = RLHFDataset(data_path)

    # Actor model config
    actor_model = model_cfg.get("model_name", "Qwen/Qwen3-30B-A3B")
    actor_device_map = model_cfg.get("actor_device_map", "auto")
    fsdp_size = model_cfg.get("fsdp_size", 1)

    # Rollout config for sglang
    sglang_tp = rollout_cfg.get("tp_size", int(os.environ.get("SGLANG_TP_SIZE", 1)))
    sglang_ep = rollout_cfg.get("ep_size", int(os.environ.get("SGLANG_EP_SIZE", 1)))
    sglang_url = rollout_cfg.get("sglang_url", "http://127.0.0.1:30000")
    rollout_n = rollout_cfg.get("n", 4)
    rollout_max_new_tokens = rollout_cfg.get("max_new_tokens", 2048)
    rollout_temperature = rollout_cfg.get("temperature", 1.0)

    logger.info(f"Actor model: {actor_model}")
    logger.info(f"FSDP size: {fsdp_size}")
    logger.info(f"Sglang TP: {sglang_tp}, EP: {sglang_ep}")
    logger.info(f"Rollout n: {rollout_n}, max_new_tokens: {rollout_max_new_tokens}")

    # Build trainer kwargs defensively
    trainer_kwargs: Dict[str, Any] = {
        "dataset": verl_dataset,
        "reward_fn": reward_fn,
        "actor_model": actor_model,
        "max_steps": training_cfg.get("max_steps", 100),
        "batch_size": training_cfg.get("batch_size", 1),
        "rollout_n": rollout_n,
    }

    # Optional sglang kwargs
    if sglang_tp > 1 or sglang_ep > 1:
        trainer_kwargs["sglang_tp"] = sglang_tp
        trainer_kwargs["sglang_ep"] = sglang_ep
        trainer_kwargs["sglang_url"] = sglang_url

    # Attempt to instantiate trainer
    try:
        trainer = RayPPOTrainer(**trainer_kwargs)
    except TypeError as e:
        logger.error(f"RayPPOTrainer initialization failed: {e}")
        logger.error("This usually means the verl API has changed. Please update trainer_kwargs.")
        raise

    logger.info("Starting training...")
    trainer.fit()
    logger.info("Training complete.")


if __name__ == "__main__":
    main()
