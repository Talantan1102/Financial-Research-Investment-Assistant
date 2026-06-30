# 跨家蒸馏后处理 + 工具 train/serve 一致性 —— 调研与决策

> 2026-06-27。背景:SFT 数据由 deepseek-v4-flash 经 MCP 分组工具采集(含 reasoning_content),
> 要训 qwen3-8b(异家),且 RL rollout(verl)当前用原子工具子集(≠ SFT/生产)。
> 本文综合学术界/工业界做法 + 给出两个核心决策的推荐。WebSearch 检索,下附来源。

## TL;DR(两个 ⭐ 决策的推荐)

1. **工具界面对齐 → 必须做**。off-policy SFT 与部署的工具界面不一致会造成 train/serve skew、级联错误;tool-use RL 依赖 SFT 给的 schema literacy。让 SFT/RL/生产共用同一套 MCP 工具界面。
2. **reasoning_content → 保留但"重渲染 + 拒绝采样过滤",别原样喂;靠后续 GRPO 做 on-policy 纠偏**。这正是 DeepSeek-R1 蒸馏的配方(SFT 蒸馏 teacher CoT → RL),我们的"SFT(deepseek)→ GRPO"结构与之同构。**必做**:把 reasoning 重渲染进 qwen3 `<think>` + tool_calls 转 Hermes 格式。

---

## (1) 跨家格式/模板后处理:重渲染是标配

- **工具调用格式**:Qwen3 原生用 **Hermes 式 `<tool_call>` XML**,其 tokenizer chat_template 内置 Hermes 工具支持;官方建议"用 Hermes 式工具调用最大化 Qwen3 function-calling 性能"。vLLM 有 `--tool-call-parser hermes` 原生解析。→ **把我们存的结构化 OpenAI `tool_calls` 重渲染成 qwen3 chat_template 的 Hermes 格式**(SFT 框架套学生模板即可,但 reasoning_content 是非标字段,需显式处理,见(2))。来源:[Qwen Function Calling 文档](https://qwen.readthedocs.io/en/latest/framework/function_call.html)。
- **已知失败模式**:"SFT 常教会的是**格式而非实质**"(模型模仿推理路径但不真懂)→ 跨家时尤甚。来源:[Effectiveness of CoT in Distilling Reasoning](https://arxiv.org/pdf/2511.05184)。

## (2) CoT 跨家处理:保留 teacher CoT 可行,但要"筛 + 重渲染",并知其风险

- **正例(保留可行)**:**DeepSeek-R1 蒸馏**就是把 teacher CoT 直接 SFT 进 Qwen/Llama 异家学生——**~800K 样本(600K 推理经拒绝采样筛正确 + 200K 通用),2 epoch SFT,蒸馏阶段不加 RL**。证明"保留 teacher CoT"在**有拒绝采样筛选 + 规模**下有效。来源:[DeepSeek-R1 论文](https://arxiv.org/html/2501.12948v1)、[DeepSeek-R1-Distill-Qwen-32B(HF)](https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Qwen-32B)。
- **风险(为何不能原样喂)**:① **分布失配**——teacher 长 CoT 的不确定性/冗余常超学生容量;teacher 不知学生容量。② **exposure bias**——off-policy SFT 在 teacher 轨迹上训,与学生推理分布不相交 → 偏离即级联错误。来源:[On-Policy Distillation 综述](https://arxiv.org/html/2604.00626v1)、[Local Naturalness 选 teacher 数据](https://arxiv.org/html/2510.03988v1)。
- **缓解配方**:按学生"local naturalness"/在原题表现**自适应筛选** teacher 轨迹(ACoTD、NaturalThoughts);跨家专门工作 [Breaking the Tokenizer Barrier: On-Policy Distillation across Model Families](https://arxiv.org/html/2606.09456)。

## (3) 拒绝采样(RFT/STaR/ReST/RAFT)+ on-policy:我们有 oracle,天生适配

- **RFT 定义**:只把**自生成且满足可验证成功判据**的轨迹纳入每轮 SFT;无需 RL/奖励模型。变体:**STaR、ReST、RAFT、RSO、Hint-RFT**。来源:[RFT(emergentmind)](https://www.emergentmind.com/topics/rejection-sampling-fine-tuning-rft-ad4c417c-416b-40b6-bf9a-4653b83ddcfb)。
- **on-policy distillation(OPD)**:用**学生自己采**的轨迹训,消除 exposure bias;**Qwen3、MiMo、GLM 均已把 OPD 纳入后训并报告显著提升**。来源:[On-Policy Distillation 综述](https://arxiv.org/html/2604.00626v1)、[awesome-on-policy-distillation](https://github.com/chrisliu298/awesome-on-policy-distillation)。
- **对我们**:我们有 **oracle(judge)+ 题目 + 跑 qwen 的 infra(base 分带)** → 可做 RFT:用 **同家 qwen(8B 自己或 qwen3-235B)** 重采、oracle 只留对的 → 数据落在学生分布内,**同时消除跨家风格 + 工具界面 skew**(若经 MCP 跑)。这是最干净路径,代价是重采成本。

## (4) 工具型模型 train/serve 一致性:不一致会掉点

- **off-policy 工具数据 → train/deploy 失配**:"agent 从非自己生成的轨迹学 → 训练与部署行为失配"。有效的 tool-use RL **都用 SFT 暖启**给 schema literacy(工具语法/schema 认知)。来源:[Agentic RL Primer(aman.ai)](https://aman.ai/primers/ai/agentic-RL/)、[Demystifying RL in Agentic Reasoning](https://arxiv.org/html/2510.11701v1)。
- **约束解码绑 schema**:推理时切到 constrained decoding,token 受**预定义 JSON Schema** 约束 → **训练/部署 schema 不一致 = 直接失配**。
- **工业数据线强调统一+可验证 schema**:APIGen(多阶段生成+可执行校验)、ToolACE(自演化+分层校验)、xLAM(大动作空间)、LoopTool(闭合数据-训练环)。共识是**工具 schema 统一 + 执行校验**。来源:[ToolACE](https://arxiv.org/html/2409.00920v2)、[xLAM](https://github.com/SalesforceAIResearch/xLAM)、[LoopTool](https://arxiv.org/html/2511.09148v1)。
- **直接含义**:我们"SFT 用 MCP 分组工具集 + search_tools,RL 用 verl 原子子集"= 教科书式 train/serve skew,应对齐。

---

## 据此回填合并清单的两个 ⭐ 决策

**⭐ 决策1:工具界面 → 对齐(A 方案,RL 经 MCP)。** 依据(1)(4):off-policy + schema 失配会掉点,约束解码绑 schema。优先级:RL 前必做。

**⭐ 决策2:reasoning_content → 三步走(对齐 R1 配方 + 我们已有 oracle)**:
- **必做**:① reasoning 重渲染进 qwen3 `<think>`(别丢、别原样喂 deepseek 格式)② tool_calls 转 Hermes ③ 只留 clean∧correct(我们已做=拒绝采样式筛选,符合 R1"600K 经拒绝采样")。
- **结构上**:我们"SFT(deepseek 蒸馏)→ GRPO(on-policy)"与 **DeepSeek-R1 配方同构**——GRPO 阶段本就是 on-policy,天然纠 off-policy SFT 的 exposure bias。所以**保留筛过的 teacher CoT 暖启 + GRPO 纠偏**是站得住的。
- **增强(可选,要质量再上)**:对低通过/高价值意图做 **RFT**——同家 qwen 经 MCP 重采、oracle 验——既去跨家风格又去工具 skew。

**一句话**:学术界/工业界先例支持"**对齐工具界面(必做)+ 保留筛过的 teacher CoT 重渲染暖启 + 靠 GRPO on-policy 纠偏**";要更高质量再叠 **RFT(同家重采)**。我们的两阶段结构本身就对(同 R1),缺的是①工具对齐 ②重渲染 这两道工。

## 主要来源
- DeepSeek-R1(蒸馏配方):https://arxiv.org/html/2501.12948v1 · https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Qwen-32B
- On-Policy Distillation 综述:https://arxiv.org/html/2604.00626v1 · https://github.com/chrisliu298/awesome-on-policy-distillation
- 跨家 OPD:https://arxiv.org/html/2606.09456
- 选 teacher 数据(local naturalness):https://arxiv.org/html/2510.03988v1 · CoT 蒸馏有效性:https://arxiv.org/pdf/2511.05184
- RFT/STaR/ReST:https://www.emergentmind.com/topics/rejection-sampling-fine-tuning-rft-ad4c417c-416b-40b6-bf9a-4653b83ddcfb
- 工具型 RL/数据:https://aman.ai/primers/ai/agentic-RL/ · https://arxiv.org/html/2510.11701v1 · https://arxiv.org/html/2409.00920v2 · https://github.com/SalesforceAIResearch/xLAM · https://arxiv.org/html/2511.09148v1
- Qwen function calling(Hermes):https://qwen.readthedocs.io/en/latest/framework/function_call.html
