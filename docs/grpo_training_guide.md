# AgentFlow GRPO 训练指南（verl + sglang）

本文档介绍如何在 AgentFlow 中使用 **GRPO（Group Relative Policy Optimization）** 训练 **Qwen3-30B-A3B** 多轮工具调用模型，基于 **verl** 分布式 RL 框架和 **sglang** 推理引擎。

---

## 1. 架构概览

```
┌─────────────────────────────────────────────────────────────────────┐
│                        AgentFlow GRPO Pipeline                       │
├─────────────────────────────────────────────────────────────────────┤
│  Stage 1: Data Synthesis                                             │
│    synthesis/pipeline.py → trajectories.jsonl + synthesized_qa.jsonl │
├─────────────────────────────────────────────────────────────────────┤
│  Stage 2: GRPO Data Conversion                                       │
│    scripts/pipeline/convert_to_grpo.py → grpo_data.jsonl            │
├─────────────────────────────────────────────────────────────────────┤
│  Stage 3: verl Dataset Building                                      │
│    training/verl/data/build_verl_dataset.py → verl_data.jsonl       │
├─────────────────────────────────────────────────────────────────────┤
│  Stage 4: GRPO Training (verl + sglang)                              │
│    training/verl/train_grpo.py                                       │
│    • FSDP Actor  (policy model training)                             │
│    • sglang Rollout (batch generation)                               │
│    • AgentFlowReward (sandbox-based reward)                          │
└─────────────────────────────────────────────────────────────────────┘
```

核心设计决策：
- **Reward 阶段重放 Tool Calls**：sglang 只负责在 GPU 上批量生成文本，实际的工具调用在 CPU reward worker 中通过 sandbox 重新执行。这保证了 GPU 利用率最大化，同时正确验证轨迹质量。
- **Session 隔离**：每条 trajectory 使用独立的 `worker_id` 创建 sandbox session，执行完成后立即销毁，避免交叉污染。

---

## 2. 目录结构

```
training/
├── reward/                          # 奖励模块（核心新增）
│   ├── __init__.py                  # AgentFlowReward 统一入口
│   ├── parser.py                    # 从生成文本解析 <tool_call>
│   ├── trajectory_executor.py       # 在 sandbox 中重放 tool calls
│   ├── rule_reward.py               # 规则奖励（accuracy / efficiency / format）
│   ├── llm_judge_reward.py          # LLM 评判奖励（开放式任务）
│   ├── hybrid_reward.py             # 混合奖励调度
│   └── ground_truth_cache.py        # Ground Truth 缓存
├── verl/                            # verl 训练集成
│   ├── train_grpo.py                # 主训练脚本
│   └── data/
│       └── build_verl_dataset.py    # 构建 verl 兼容数据集
└── scripts/                         # 启动脚本
    ├── prepare_data.sh              # 一键数据准备
    ├── launch_grpo_4xa100.sh        # 4x A100 分布式训练
    └── launch_grpo_8xh20.sh         # 8x H20 分布式训练

configs/training/                    # 训练配置
├── grpo_qwen3_30b_smoke.yaml       # 单 GPU 冒烟测试
├── grpo_qwen3_30b_4xa100.yaml      # 4x A100 配置
├── grpo_qwen3_30b_8xh20.yaml       # 8x H20 配置
└── reward_config.yaml              # 奖励函数配置
```

---

## 3. 快速开始

### 3.1 环境准备

安装核心依赖（假设已安装 AgentFlow 基础环境）：

```bash
# 安装 verl（ByteDance 开源分布式 RL 框架）
# 请参考官方仓库: https://github.com/volcengine/verl
pip install verl

# 安装 sglang（推理引擎）
pip install sglang
```

启动 sandbox 服务器：

```bash
./start_sandbox_server.sh --config configs/sandbox-server/finance_research_config.json
```

### 3.2 一键数据准备

```bash
bash training/scripts/prepare_data.sh
```

该脚本会自动执行：
1. 运行数据合成 pipeline（默认使用 `configs/synthesis/temp_grpo_20_seeds.json`）
2. 转换为 GRPO 格式
3. 构建 verl 兼容数据集到 `data/verl_training_data.jsonl`

### 3.3 Smoke Test（无 verl 依赖）

先验证 reward 模块和数据 pipeline 是否能正常工作：

```bash
python training/verl/train_grpo.py \
    --config configs/training/grpo_qwen3_30b_smoke.yaml \
    --no-verl
```

此模式会：
- 加载数据集
- 对前 2 条样本执行 `AgentFlowReward` smoke test
- 不启动真正的分布式训练

### 3.4 单 GPU / 小规模训练验证

```bash
python training/verl/train_grpo.py \
    --config configs/training/grpo_qwen3_30b_smoke.yaml \
    --max-steps 2 \
    --rollout-n 2
```

### 3.5 分布式训练

**4x A100 80GB：**

```bash
sbatch training/scripts/launch_grpo_4xa100.sh
```

**8x H20：**

```bash
bash training/scripts/launch_grpo_8xh20.sh
```

---

## 4. 奖励模块详解

### 4.1 Tool Call 解析

模型生成文本中的 tool call 采用结构化标签：

```text
步骤 1：查询贵州茅台的实时股价
<tool_call>
{"name": "market_data.get_quote", "arguments": {"symbol": "600519.SH"}}
</tool_call>
```

`parser.py` 负责从原始文本中提取这些调用，并还原为多轮对话结构。

### 4.2 Trajectory 重放

`trajectory_executor.py` 在 reward 阶段完成以下操作：
1. 解析模型输出，提取所有 tool calls
2. 为当前 trajectory 创建独立 sandbox session
3. 顺序执行每个 tool call，收集返回结果
4. 打包为 trajectory dict，供 rewards 计算使用

### 4.3 奖励路由

`AgentFlowReward` 根据 seed 标签中的 `verifiable` 和 `verification_method` 字段，自动选择奖励策略：

| 任务类型 | `verifiable` | `verification_method` | 使用的 Reward 类 |
|---------|-------------|----------------------|-----------------|
| 可验证查询 | `true` | `api` / `compute` | `RuleBasedReward` |
| 半开放式 | `true` | `hybrid` | `HybridReward` |
| 全开放式 | `false` | `llm_judge` | `LLMJudgeReward` |

### 4.4 Rule-Based Reward 组成

- **Accuracy（准确性）**：对比可验证字段（如股价、PE）与 ground truth，支持容差。
- **Efficiency（效率）**：惩罚工具数过少/过多、轮次超限。
- **Format（格式）**：检查输出是否有推理过程和明确结论。

权重默认：`accuracy 0.6 + efficiency 0.3 + format 0.1`

---

## 5. MOE 模型专属配置（Qwen3-30B-A3B）

Qwen3-30B-A3B 是 **30B 总参数 / 3B 激活参数** 的 MOE 模型，sglang 需配置 Tensor Parallelism（TP）和 Expert Parallelism（EP）。

推荐配置：

| 硬件 | Actor (FSDP) | Rollout (sglang) | TP | EP |
|------|-------------|-------------------|----|----|
| 4x A100 80GB | 2 GPUs | 2 GPUs | 2 | 2 |
| 8x H20 | 4 GPUs | 4 GPUs | 4 | 4 |

cf. `configs/training/grpo_qwen3_30b_4xa100.yaml` / `8xh20.yaml`

---

## 6. 关键接口说明

### 6.1 AgentFlowReward

兼容 verl 的 `reward_fn` 签名：

```python
from training.reward import AgentFlowReward

reward_fn = AgentFlowReward(
    sandbox_server_url="http://127.0.0.1:18890",
    resource_types=["unified_finance"],
)

rewards = reward_fn(prompts, responses, metadata)
# returns: np.ndarray, shape (batch_size,), dtype float32
```

### 6.2 train_grpo.py 参数

```bash
python training/verl/train_grpo.py \
    --config CONFIG_PATH          # 训练配置文件（必填）
    --max-steps N                 # 覆盖最大训练步数
    --rollout-n N                 # 覆盖 GRPO group size
    --data-path PATH              # 覆盖数据集路径
    --no-verl                     # 仅跑 smoke test，不导入 verl
```

---

## 7. 调试与排错

| 问题 | 排查方向 |
|------|---------|
| Reward smoke test 失败 | 检查 sandbox server 是否已启动；检查 `sandbox_server_url` 配置 |
| `ImportError: verl` | 未安装 verl，或需要 `--no-verl` 模式 |
| sglang OOM / crash | 降低 `gpu_memory_utilization`；减小 TP/EP；使用半精度 |
| Tool call 解析为空 | 检查模型输出格式是否与 `<tool_call>` 标签匹配；chat template 是否正确 |
| Sandbox session 泄漏 | 确认 trajectory_executor 的 `finally` 块执行了 `sandbox.close()` |
| Ray hang | 设置 `RAY_worker_register_timeout_seconds=600`；检查网络端口占用 |

---

## 8. 参考文档

- `docs/grpo_label_system_design.md` - 原始奖励体系设计文档
- `rollout/core/runner.py` - 多轮对话执行的参考实现
- `sandbox/tool_schemas/__init__.py` - 可用工具及其参数定义
- `docs/CLAUDE.md` - AgentFlow 整体架构介绍

---

## 9. TODO / 已知限制

1. `train_grpo.py` 中的 `RayPPOTrainer` 初始化参数是基于 verl 通用 API 推测编写，实际使用时可能需要根据本地 verl 版本微调。
2. LLM Judge Reward 需要配置外部 LLM API Key 才能正常工作；未配置时回退到 0.5 中性奖励。
3. 当前冒烟测试数据集为 20 seeds，完整训练建议使用 `configs/synthesis/grpo_100k_config.json` 生成更大规模数据。
