# RL 基座模型选型调研 + 决策(2026-06-22)

> 背景:本项目的 chatloop 工具调用 agent,pre-RL 基线 deepseek-v4-flash 89.4%,残留=工具调用可靠性=RL 靶子。本轮决定 RL 训练用哪个基座小模型。

## 决策

**RL 基座 = Qwen3-8B-Instruct**(HuggingFace 上的 post-trained `Qwen3-8B`,非 `-Base`)。
路线:**instruct 基座 → SFT 热启动(本仓的干净轨迹底料)→ GRPO(verl-agent)+ indicator_oracle 可验证奖励**。

## 调研结论(带来源)

### ① 工业界/学术界小模型自训 RL 的事实标准 = Qwen 系列
- 绝大多数 RLVR(可验证奖励 RL)论文用 Qwen2.5-7B / Qwen2.5-Math-7B 当基座,算法清一色 GRPO/DAPO。([RLVR 综述](https://www.promptfoo.dev/blog/rlvr-explained/)、[1-shot RLVR](https://openreview.net/forum?id=IBrRNLr6JA))
- Agentic/工具调用 RL 同样 Qwen 为主;DeepSeek-V3.2 在 8.5 万 agentic 工具任务上做大规模 RL。
- 选 Qwen 的原因:Apache-2.0、完整尺寸梯队、工具调用底子好、所有 RL 框架默认支持。

### ② 从 instruct 起跑,不从裸 base
- 主流最佳实践是 **SFT → RL 顺序**;模型必须先会听指令,RLHF 管线才跑得起来。([RLHF Book](https://rlhfbook.com/c/04-instruction-tuning))
- 裸 base 直接 RL(R1-Zero 式)是例外;连 DeepSeek-R1 正式版也先 cold-start SFT。

### ③ 算法 + 框架
- 算法 **GRPO**(去 value function;ToolRL 用 GRPO 比基座 +17% 且泛化优于 SFT)。([ToolRL](https://arxiv.org/pdf/2505.01441))
- 框架 **verl**(字节,HybridFlow 开源版);工具调用专用 **verl-agent / VerlTool**(GRPO/DAPO/GSPO/GiGPO)。([verl-agent](https://github.com/langfengQ/verl-agent)、[VerlTool](https://arxiv.org/html/2509.01055v1))

### ④ verl 对 Qwen3-8B 的支持
- verl 文档列 Qwen2.5/Llama3.1/Gemma2/DeepSeek,但训练走 FSDP/Megatron、rollout 走 vLLM/SGLang——**Qwen3 全系被 vLLM/SGLang 支持即可训**;SGLang RL 组明确做多轮 agentic RL。([verl](https://github.com/verl-project/verl))

### ⑤ 为什么是 8B 而不是更小
- RLVR 偏向**放大基座已有能力,而非教新能力**([Reasoning or Memorization](https://arxiv.org/pdf/2507.10532));qwen3-8b 当前 15.6% 说明"会用工具"信号存在、可放大;3B/4B 可能弱到没信号可放大(多步+run_python 任务能力 floor 高)。
- 备选对照:Qwen3-4B-Instruct-2507(成本下限)、Qwen3-30B-A3B(MoE 仅 3B 激活,能力更强、训练成本接近小模型)。

## 可直接抄的 recipe
《Demystifying RL for Long-Horizon Tool-Using Agents: A Comprehensive Recipe》([arxiv 2603.21972](https://arxiv.org/pdf/2603.21972)):**两阶段——简单题 SFT,难题 Async-GRPO**,与本项目"SFT 热启动 + 难度课程"一一对应。多篇论文已在 Qwen3 1.7B/4B/8B/14B 上做 GRPO 工具调用对比([ResT](https://arxiv.org/pdf/2509.21826)、[OpenTable-R1](https://arxiv.org/pdf/2507.03018))。

## 实操注意
1. 用 instruct/post-trained 变体(`Qwen3-8B`,非 `Qwen3-8B-Base`)。
2. `enable_thinking=false` 与现有 harness 保持一致;思考模式开关是单独的实验维度。
3. 先 SFT 把"会用工具"种进去,再 GRPO 放大——别指望 RL 凭空教会写对 run_python。
4. 评测集:主仓 141 题已合 main;v2 扩量 339 题在 worktree 待合,可作 GRPO 采样池(同题多采样比好坏的形状天然契合)。
