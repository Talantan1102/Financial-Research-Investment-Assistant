# AgentFlow：基于 GRPO 的多轮工具调用大模型训练

**定位**：端到端的 Agent 数据合成 + GRPO 训练框架，用于提升大模型在多轮对话中调用工具的能力。

---

## 1. 项目动机

当前主流 Agent 训练面临的核心问题：

| 问题 | 说明 |
|------|------|
| **数据稀缺** | 高质量多轮 tool-calling 数据难以获取，人工标注成本高 |
| **奖励设计难** | 不同于数学题有确定答案，工具调用的正确性、效率、路径选择都需要评估 |
| **训练-推理割裂** | 训练时用 vLLM/sglang 生成 rollout，但工具调用结果需要真实环境验证 |

AgentFlow 的解决思路：**自动化合成数据 → 多维度奖励函数 → GRPO 在线训练**，形成闭环。

---

## 2. 系统架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         AgentFlow Pipeline                          │
│                                                                     │
│  ┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐  │
│  │   Seed    │───▶│ Trajectory│───▶│    QA     │───▶│   GRPO    │  │
│  │ Generation│    │ Sampling  │    │ Synthesis │    │ Training  │  │
│  │  10万条   │    │  Agent探索 │    │ 多跳问答  │    │ verl+sglang│  │
│  └───────────┘    └───────────┘    └───────────┘    └───────────┘  │
│       ▲                │                │                │         │
│       │           Sandbox              │          ┌─────┴──────┐  │
│       │          (工具执行)             │          │   Reward   │  │
│       │                                │          │ Calculator │  │
│       │                                │          └─────┬──────┘  │
│       │                                │           ┌────┼────┐    │
│       │                                │         Rule  LLM Hybrid │
│       └────────────────────────────────┘           └────┴────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

全链路：**Seed 生成 → 轨迹采样 → 轨迹筛选 → QA 合成 → 格式转换 → GRPO 训练**

---

## 3. 数据工程

### 3.1 数据漏斗

```
100,000 Seeds（金融投研问题）
    │
    ▼  TrajectorySampler（LLM 驱动，Sandbox 执行）
~10,000 Trajectory Trees
    │
    ▼  TrajectorySelector（深度/信息丰富度/多样性评分）
~5,000 Selected Trajectories
    │
    ▼  QASynthesizer（多跳推理 QA 生成）
4,723 QA Pairs + Reasoning Steps
    │
    ▼  convert_to_grpo.py → build_verl_dataset.py
GRPO Training Data（messages 格式）
```

**关键数字**：10 万 seed → 4,723 QA（~5% 转化率），保证了数据质量。

### 3.2 Seed 设计

每个 seed 不是简单的 prompt，而是带有结构化元信息的任务描述：

```json
{
  "content": "天赐材料跟通威股份到底哪个更值得买？",
  "slots": {
    "user_type": "小白",
    "intent": "问买卖",
    "context": "空仓观望",
    "style": "求证型"
  },
  "entities": {
    "stocks": [{"name": "天赐材料", "code": "002709.SZ"}, {"name": "通威股份", "code": "600438.SH"}],
    "concepts": ["估值对比"]
  }
}
```

slot 和 entity 的组合保证了 seed 的多样性，避免生成重复的训练数据。

### 3.3 轨迹采样

TrajectorySampler 的核心是 **LLM 驱动的环境探索**：

1. LLM 根据 seed 决定调用哪个工具
2. Sandbox 执行工具调用，返回真实结果
3. LLM 根据结果决定下一步（分支探索，branching_factor=2）
4. 重复直到达到 max_depth=10 或 LLM 判断任务完成

产物是一棵 **轨迹树**（非线性），每个节点记录：`intent → action → observation`。

### 3.4 训练数据格式

最终转换为多轮对话格式：

```json
{
  "prompt": "<|im_start|>system\n你是金融研投助手...<|im_end|>\n<|im_start|>user\n天赐材料和通威股份哪个成交金额更高？<|im_end|>\n",
  "response": "步骤 1：查询天赐材料的股票代码\n<tool_call>\n{\"name\": \"market_data.search_stock\", \"arguments\": {\"keyword\": \"天赐材料\"}}\n</tool_call>\n...",
  "metadata": {
    "question": "...",
    "answer": "天赐材料",
    "trajectory_id": "src_0001_traj_0",
    "tags": { "verifiable": true, "verification_method": "api" }
  }
}
```

---

## 4. GRPO 训练设计

### 4.1 为什么选 GRPO

| 方法 | 优点 | 缺点 |
|------|------|------|
| SFT | 简单直接 | 只学一条路径，无法探索更优策略 |
| PPO | 经典 RLHF | 需要 Critic 模型，训练不稳定，资源翻倍 |
| DPO | 离线，高效 | 需要偏好对，无法在线探索 |
| **GRPO** | **无 Critic，组内相对排序** | 需要好的奖励函数 |

GRPO 的核心优势：**不需要训练额外的 Critic/Value 模型**，直接用同一 prompt 采样 N 个 response，组内计算相对优势（advantage），用于更新策略。

### 4.2 训练循环

```
for each training step:
    1. 从数据集采样一个 batch 的 prompts
    2. sglang 对每个 prompt 生成 N=4 个 responses（rollout）
    3. AgentFlowReward 对每个 response 计算奖励分数
    4. 组内归一化：advantage_i = (reward_i - mean) / std
    5. 策略梯度更新：maximize Σ advantage_i * log π(response_i | prompt_i)
    6. KL 惩罚：防止偏离参考策略太远
```

### 4.3 训练配置（4×A100 80GB）

```yaml
# Actor: FSDP 分布式训练（2 GPU）
model:
  model_name: Qwen/Qwen3-30B-A3B   # 30B 总参 / 3B 激活（MoE）
  fsdp_size: 2

# Rollout: sglang 推理（2 GPU）
rollout:
  n: 4                              # 每个 prompt 采样 4 个 response
  tp_size: 2                        # Tensor Parallelism
  ep_size: 2                        # Expert Parallelism（MoE 专用）
  max_new_tokens: 2048
  temperature: 1.0                  # 采样温度，鼓励探索

# 训练超参
training:
  max_steps: 500
  batch_size: 4
  learning_rate: 1.0e-6
```

**GPU 分配策略**：4 卡中 2 卡跑 FSDP Actor（参数更新），2 卡跑 sglang Rollout（推理生成）。Actor 和 Rollout 在不同阶段交替使用 GPU（verl 的 colocate 模式）。

---

## 5. 奖励函数设计（核心亮点）

### 5.1 设计难点

与数学推理不同，tool-calling 的奖励设计面临几个独特挑战：

- **答案不唯一**：查股价可以先查代码再查价格，也可以直接搜索
- **过程很重要**：调用了正确的工具但参数错误，应该给部分分
- **效率要惩罚**：能 2 步完成的用了 8 步，即使结果正确也不好
- **开放式任务**：投资建议没有标准答案

### 5.2 三层奖励架构

```
AgentFlowReward
├── RuleBasedReward     ← 可验证任务（占 40%）
│   ├── Accuracy  (0.6)   对比 API 返回的 ground truth
│   ├── Efficiency(0.3)   工具数量/轮次是否在合理区间
│   └── Format    (0.1)   是否有推理过程和结论
│
├── LLMJudgeReward      ← 开放式任务（占 15%）
│   └── 多维度 0-10 评分（信息完整性/数据支撑/逻辑/实用性）
│
└── HybridReward        ← 半开放式任务（占 45%）
    ├── Rule 部分：可验证字段用规则评
    └── LLM 部分：质量维度用 LLM 评判
```

路由逻辑基于 seed 的 `tags.verifiable` 和 `tags.verification_method` 字段自动选择。

### 5.3 Reward 阶段的工具重放

**关键设计决策**：sglang 只负责文本生成，不执行工具调用。工具调用在 CPU 端的 reward worker 中通过 Sandbox 重放。

```
sglang (GPU)              Reward Worker (CPU)
    │                           │
    ├─ 生成 response ──────────▶│
    │  (含 <tool_call> 标签)    │
    │                           ├─ 解析 tool calls
    │                           ├─ 创建隔离 Sandbox session
    │                           ├─ 顺序执行每个 tool call
    │                           ├─ 收集执行结果
    │                           ├─ 计算奖励分数
    │                           ├─ 销毁 session
    │                           │
    │◀── reward scores ─────────┤
```

这样设计的好处：
- GPU 利用率最大化（不阻塞等待工具返回）
- 奖励计算基于真实执行结果，而非模型幻觉
- Session 隔离避免不同 trajectory 间的状态污染

---

## 6. sglang 在训练中的角色

### 6.1 为什么用 sglang 而不是 vLLM

| 特性 | sglang | vLLM |
|------|--------|------|
| **RadixAttention** | 有（KV cache 树状复用） | 无 |
| **MoE EP 支持** | 原生支持 | 有限 |
| **多轮对话** | RadixAttention 天然加速共享 prefix | 需要重新计算 |
| **verl 集成** | 官方支持 | 官方支持 |

对于多轮 tool-calling 场景，sglang 的 **RadixAttention** 是关键优势：同一 prompt 的 N 个 rollout 共享 prefix 的 KV cache，避免重复计算。

### 6.2 sglang 在 GRPO 中的具体工作

```python
# verl 内部的 rollout 流程（简化）
for prompts_batch in dataloader:
    # sglang 批量生成 N 个 response per prompt
    # RadixAttention: 相同 prompt 的 N 个采样共享 prefix KV cache
    responses = sglang_engine.generate(
        prompts_batch,
        n=4,                    # GRPO group size
        temperature=1.0,        # 鼓励多样性
        max_new_tokens=2048,
        top_p=0.95,
    )
    # responses shape: (batch_size * N,)
```

### 6.3 MoE 模型的并行策略

Qwen3-30B-A3B 是 MoE 模型（30B 总参 / 3B 激活），sglang 中配置：

- **Tensor Parallelism (TP=2)**：将 Attention 和 FFN 权重切分到 2 个 GPU
- **Expert Parallelism (EP=2)**：将 64 个 Expert 分配到 2 个 GPU，每个 GPU 处理 32 个 Expert

TP 和 EP 可以组合使用，TP 切模型宽度，EP 切 Expert 数量。

---

## 7. 关键代码模块

| 模块 | 路径 | 行数 | 职责 |
|------|------|------|------|
| AgentFlowReward | `training/reward/__init__.py` | 153 | 统一奖励入口，verl 兼容接口 |
| ToolCallParser | `training/reward/parser.py` | 186 | 从模型输出解析 `<tool_call>` |
| TrajectoryExecutor | `training/reward/trajectory_executor.py` | 139 | Sandbox 中重放工具调用 |
| RuleBasedReward | `training/reward/rule_reward.py` | 196 | 准确性/效率/格式规则评分 |
| LLMJudgeReward | `training/reward/llm_judge_reward.py` | 195 | LLM 多维度质量评判 |
| HybridReward | `training/reward/hybrid_reward.py` | 103 | 规则+LLM 混合策略 |
| convert_to_grpo.py | `scripts/pipeline/convert_to_grpo.py` | 303 | 合成数据 → GRPO 格式 |
| SynthesisPipeline | `synthesis/pipeline.py` | ~400 | 三阶段数据合成管道 |

---

## 8. 面试问答准备

### Q1: 为什么选择 GRPO 而不是 SFT 或 DPO？

> SFT 只学一条路径，模型无法探索更优的工具调用策略。DPO 需要离线构造偏好对，无法利用在线生成的多样化轨迹。GRPO 的优势在于：无需额外的 Critic 模型（相比 PPO 省一半 GPU），通过组内相对排序天然利用 N 个 rollout 的多样性，且奖励函数可以直接用规则验证，不需要训练 reward model。

### Q2: 奖励函数怎么设计的？为什么这样设计？

> 借鉴了 Kimi K2 的"可验证奖励 + 自我批评"双轨制。可验证任务（查股价、查 PE）用规则直接验证准确性；开放式任务（投资建议）用 LLM Judge 多维度评分；半开放式任务用混合策略。每种奖励都包含效率惩罚（防止过度调用工具）和格式检查（保证推理结构）。关键设计决策是在 CPU 端重放工具调用来验证，而不是信任模型的文本输出。

### Q3: sglang 在这里起什么作用？和 vLLM 比有什么优势？

> sglang 做 GRPO 的 rollout 生成——对每个 prompt 采样 N=4 个 response。核心优势是 RadixAttention：同一 prompt 的 4 个采样共享 prefix 的 KV cache，避免重复计算。对于多轮 tool-calling 场景，前面几轮的对话历史是共享的，RadixAttention 在这里加速非常明显。另外 sglang 对 MoE 的 Expert Parallelism 支持更成熟。

### Q4: 训练数据是怎么生成的？

> 三阶段管道：(1) TrajectorySampler 用 LLM 驱动 Agent 在 Sandbox 中探索，构建轨迹树；(2) TrajectorySelector 按深度、信息丰富度、工具多样性打分筛选；(3) QASynthesizer 基于筛选后的轨迹生成多跳推理 QA。从 10 万 seed 最终生成 ~5000 条高质量训练数据，5% 的转化率保证了质量。

### Q5: 如何保证训练数据质量？

> 多层过滤：seed 阶段有 slot/entity 的多样性控制和异常标记；轨迹阶段有最小深度、路径相似度去重（threshold=0.8）、信息丰富度评分；QA 阶段有多跳推理步骤的完整性验证和反捷径检查。最终 10 万 seed 只有 5% 通过全部筛选。

### Q6: 分布式训练是怎么做的？

> 基于 verl（字节开源）+ Ray 的架构。4 张 A100 分两组：2 张用 FSDP 做 Actor 模型的参数更新，2 张用 sglang 做 rollout 推理。Actor 和 Rollout 在 verl 的 colocate 模式下交替使用 GPU 资源。Qwen3-30B-A3B 是 MoE 模型，sglang 配置 TP=2（切模型宽度）+ EP=2（切 Expert 数量）。
