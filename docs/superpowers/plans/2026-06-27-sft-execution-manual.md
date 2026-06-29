# SFT 执行手册(qwen3-8b LoRA 暖启,D4 数据)

> 2026-06-27。把 D4 的 3400 条 SFT 数据微调进 Qwen3-8B(LoRA),作为 GRPO 前的暖启。
> 调研支撑见 `docs/research/2026-06-27-cross-family-distill-and-tool-alignment.md` + 本文末尾引用。

## 0. 一句话本质

给模型看 3400 条「问题 + 工具数据 → (deepseek 示范的)思考+工具调用+答案」,微调权重让它**模仿**。
我们的两阶段 = **SFT 暖启(本文)→ GRPO(on-policy 纠偏)**,与 DeepSeek-R1 配方同构。

**SFT 是纯灌输(teacher forcing),不生成**:
- **不用 sglang、不用 tool_server、不连 tushare**——工具调用/返回都是数据里**冻住的文本**(采轨时已记)。
- 模型每个位置用**真值前缀**学"下一 token",从不看自己的输出 → 故有 exposure bias,留给 GRPO 纠。
- 对比:GRPO 阶段才**真生成轨迹**(要 sglang + tool_server + 真工具,① 工具对齐就是为它)。
- 含义:SFT 轻(单机 forward/backward 算 loss 即可),但 SFT 学的工具调用格式必须 == RL 真跑的(② 同模板已保证)。

## 1. 喂什么 + 怎么渲染

- 数据:`backend/eval/question_gen/data/d4_overnight/sft_train.jsonl`(3400 条多轮 messages)。
- 渲染:**qwen3 `apply_chat_template`**(原生把 deepseek `reasoning_content`→`<think>`、OpenAI
  `tool_calls`→Hermes `<tool_call>`,已验证)。SFT/GRPO/生产**必须同一个模板**(坑⑤)。

## 2. 最关键机制:loss masking(只学 assistant)

一段对话有 user / tool / assistant。**只对 assistant token 算 loss(含 `<think>`),user/system/tool
全 mask(-100,只当上下文)**;多轮则**每个 assistant 轮都算、其余全 mask**。
- 漏了 = 模型去学"生成问题/工具输出" → 直接训废。**这是新手第一坑。**
- verl SFT:`data.multiturn.enable=True` + 用其 multiturn loss-mask(只 assistant);
  TRL 对照:`assistant_only_loss=True` / `DataCollatorForCompletionOnlyLM`。

## 3. max 序列长度(本仓实测,2026-06-27)

token 长度分布(qwen3 tokenizer,3400 条):**中位 1714 / 均值 2825 / p90 6253 / p95 8492 /
p99 12952 / max 24501**。超阈值占比:>4096=20.6% / **>8192=5.5%(187 条)** / >12288=1.1% / >16384=0.4%。

**决策:`max_len=32768`,3400 条全留(max=24501 < 32k,一条不丢)。** 这些长样本是 **clean∧correct
(passed∧自然停∧≤20 步)的正确硬样本**——长是因为 genuinely 多步难题 / 工具返回大(如 get_daily 三年
日线),不是兜圈低质,**正是模型该学的**,不丢。**绝不截断**(截断切掉末尾的最终答案 token = 残废)。
- 代价是显存(O(n²)),用**省显存三件套**扛(见 §4):gradient checkpointing + per-device batch=1 + 梯度累积 + flash-attn,可选按长度分桶让长样本单独成批。
- 过滤步退化为**安全兜底**:仅丢 token>32768 的(本数据集为 0 条)。
- token 分布参考:中位 1714 / p95 8492 / p99 12952 / max 24501;>8192 占 5.5%、>16384 占 0.4%。

## 4. LoRA 超参(直接用这套)

| 参数 | 值 | 备注 |
|---|---|---|
| rank | 16(或 32) | 3400 条中等量,16 够;复杂可 32 |
| alpha | = rank 或 2×rank | 是 LR 的隐形乘子 |
| target_modules | q/k/v/o/gate/up/down_proj | 同 verl-8b-lora 配方 |
| 学习率 | ~1e-4 | cosine 衰减 |
| warmup_ratio | 0.1 | |
| epochs | **1-3(先 2,盯 val 早停)** | 多了过拟合(坑②) |
| max_len | **32768**(全留,见 §3) | 长样本靠省显存技术扛,不丢不截 |
| per-device batch | **1 + 梯度累积**(凑有效 batch) | 单条 32k 长样本也放得下 |
| 省显存 | **gradient checkpointing + flash-attn**(必开)| 32k 序列 O(n²) 的关键;可选按长度分桶 |

## 5. 怎么跑(同 verl env,SFT 完直接接 GRPO)

verl 自带 SFT trainer(`verl.trainer.fsdp_sft_trainer`),复用 `verl-8b-lora-2card-recipe` 环境/模型路径:
1. 过滤 + 转格式:`sft_train.jsonl`(messages)→ SFT trainer 吃的格式(它内部 apply_chat_template + mask)。
2. 写 yaml/命令:模型路径 `/root/autodl-tmp/models/Qwen3-8B` + LoRA(§4)+ 数据路径 + max_len=8192。
3. 跑 → 产 LoRA adapter(GRPO 时加载,或 merge 进基模)。
4. 注:与 GRPO 同 env、同模板、同工具面(① 已对齐)→ 暖启与 RL 无缝。

## 6. 开跑前检查清单(落地动作)

- [ ] **超长兜底**:max_len=32768,仅丢 token>32768 的(本数据集 0 条,全留 3400)。
- [ ] **确认 loss mask**:抽一条渲染,确认只有 assistant 段计 loss(打印 label,非 assistant 应为 -100)。
- [ ] **确认模板一致**:SFT 用的 chat_template == ① 工具服务/GRPO 用的(都是 qwen3 原生)。
- [x] **去污染(2026-06-27 已查)**:sft_train(2061 case)vs `datasets/val`(220)/`test`(214):
  **exact case_id 0 泄漏**;语义近重(类别+股票)val=2(`qg-HHI-电气设备`/`qg-权重-电气设备`,板块组合题)、test=0
  → eval 时从 val 剔这 2 个,其余干净。
- [ ] **留出 val**:`datasets/val.jsonl`(剔 2 近重)不进训练,用于早停 + pass 率对比。

## 7. 验收(SFT 成不成的真信号)

- train loss 平稳降(非不动/非 nan);
- **val/test 集上 SFT 后 pass 率 > base 8B**(真信号,不是 loss 低就行);
- 抽查生成:qwen3 格式下正确 `<think>` + 调对工具(MCP 分组名)+ 给数值答案;
- **别为 SFT 刷分**——它只是 GRPO 的暖启,真提升靠 RL(坑⑧)。

## 8. 工业界 SFT 八坑(调研)

| # | 坑 | 避法(对我们) | 源 |
|---|---|---|---|
| 1 | loss 没 mask prompt | assistant-only loss,多轮每 assistant 都算 | [prompt loss 研究](https://arxiv.org/html/2401.13586v2) · [TRL](https://huggingface.co/docs/trl/v0.19.1/sft_trainer) |
| 2 | 过拟合/训太久 | 1-3 epoch、低 LR、盯 val 早停 | [遗忘研究](https://arxiv.org/pdf/2406.04836) |
| 3 | 灾难性遗忘 | LoRA + 后续 GRPO 治愈;可掺通用数据 | [RL heals](https://arxiv.org/html/2509.12235v2) · [改进 SFT](https://arxiv.org/abs/2506.09428) |
| 4 | LoRA 配错 | rank16/alpha=rank·2x/LR1e-4 cosine/warmup0.1 | [Unsloth 指南](https://unsloth.ai/docs/get-started/fine-tuning-llms-guide/lora-hyperparameters-guide) |
| 5 | chat template 不一致 | SFT==GRPO==生产 同 qwen3 模板 | (本仓 ② 已统一) |
| 6 | 长多轮被截断 | max_len 盖长尾或丢超长(§3) | — |
| 7 | 数据质量>数量 | 已筛 clean∧correct 3400 条 | — |
| 8 | 为 SFT 而 SFT | SFT 只做暖启,提升靠 GRPO | [Good SFT for RL](https://arxiv.org/pdf/2602.01058) |

**最该盯三个**:①loss mask(漏了训废)、②早停别过拟合、⑥别截断长轨迹。

## 9. 评估指标(我们用哪些 + 为什么)

我们有**确定性真值 oracle** + 多轮工具 agent → 直接用任务成功率,不需代理指标。

**✅ 用的(主 + 诊断)**:
| 指标 | 阶段/频率 | 为什么用 |
|---|---|---|
| **pass@1 @ oracle**(任务成功率) | SFT 后评估;每 N 步抽测;跨阶段对比 base/GRPO | **头号指标**。oracle 带容差判真值,直接量"算没算对",最真 |
| **val loss**(token CE,teacher-forced) | 训练中 | 便宜不用生成,**只做早停防过拟合**;loss 低 ≠ agent 好,不当质量指标 |
| **per-intent pass@1 拆分** | 评估时 | 总分掩盖差异(估值难/快照易,实测方差大)→ 知哪个意图弱,指导补数据 |
| **工具调用合法率**(工具名∈MCP面+参数合法 JSON) | 评估时(尤其初期) | 区分"格式坏"vs"格式对但答错";验证 ② qwen3 工具格式学会了 |
| **halt 分布 + 平均步数** | 评估时 | natural vs spinning/max_steps;步数=效率,看是否兜圈 |

**⏳ 可选(定稿/上生产前)**:**pass^k**(τ-bench 式,k 次全中=可靠性,非碰运气)。

**❌ 不用**:
| 不用 | 为什么 |
|---|---|
| BFCL 式工具序列精确/AST 匹配 | 我们多条路都能到答案,oracle 判答案不判路径 → pass@1 更合适 |
| LLM-as-judge 评答案 | 答案是数值+确定性 oracle(容差),不需更吵更贵的 LLM 裁判 |
| BLEU/ROUGE/perplexity | 对工具 agent 任务成功无意义 |

标准对照([BFCL v3/v4](https://www.spheron.network/blog/tool-calling-benchmarks-bfcl-tau-bench-latency-optimization/) · [τ-bench](https://www.emergentmind.com/topics/bfcl-v3-multi-turn-benchmark));multi-turn 15.75%→56.5% 大跳是 **RL** 带来的,SFT 只需把 base 抬一截([FunReason](https://arxiv.org/pdf/2505.20192))。
**落地**:训练盯 val loss 早停;每 N 步用现成 `run_passk`+`judge` 跑 pass@1@oracle on val(剔 2 近重),全部对比 base-8B。

## 11. 调参表(qwen3-8b LoRA)

| 参数 | 含义 | 调参目的 | 怎么调(默认 + 症状→方向) |
|---|---|---|---|
| learning_rate | 每步更新幅度 | 收敛速度 vs 稳定 | **1e-4**;loss 炸/nan/抖→降5e-5;不动→升2e-4;配 cosine |
| epochs | 数据过几遍 | 学够 vs 过拟合 | **2**;盯 val loss:回升=过拟合→早停;仍降→可到3;别超3 |
| lora_rank (r) | adapter 容量 | 欠拟合 vs 过拟合/显存 | **16**;train loss 高位平台→升32;过拟合/显存紧→降8 |
| lora_alpha | adapter 缩放(隐形 LR 乘子) | 放大/缩小 adapter | **=r 或 2r**;想更使劲→升 |
| lora_dropout | adapter 正则 | 防过拟合 | **0.05**;val≫train→升0.1;欠拟合→0 |
| warmup_ratio | LR 预热 | 稳开头 | **0.03–0.1**;开头 loss 抖/炸→升 |
| effective batch | 梯度平滑(per_device×accum×卡) | 稳定 vs 吞吐 | per_device=1(32k)+accum 凑**有效16–32**;太抖→升accum |
| weight_decay | 权重衰减 | 防过拟合 | **0.0–0.01**;过拟合→升 |
| lr_scheduler | LR 曲线 | 末段细调 | **cosine** |
| (数据)intent 配比 | 各意图占比 | 补弱意图 | 某类 pass@1 特低→上采/补数据(非超参) |

**调参顺序(别一次全动)**:① 先定 LR+epochs(最大杠杆) → ② 欠拟合升 rank → ③ 过拟合升 dropout/wd 或减 epochs → ④ 不稳降 LR/升 warmup/升有效 batch → ⑤ 某意图弱走数据侧上采。**判据**:train loss + val loss(早停)+ 周期 pass@1@oracle(真信号)。

## 10. 省显存 + 训练加速(32k 序列必备)

**省显存**([Anyscale](https://docs.anyscale.com/llm/fine-tuning/speed-and-memory-optimizations) · [Liger](https://www.spheron.network/blog/liger-kernel-llm-training-gpu-cloud/)):
| 手段 | 作用 | 我们 |
|---|---|---|
| flash-attention | attn O(n²)→O(n) | **必开**(32k 命) |
| gradient checkpointing | 重算激活 | **必开**(32k 命) |
| FSDP + 优化器 CPU offload | 分片 2 卡 + 优化器卸 CPU | 必用 |
| bf16 | 省一半 | 必用 |
| Liger kernel | 融合核,**省 60% 显存** | 强烈建议 |
| 8-bit 优化器 / QLoRA(4bit 基模) | 优化器/基模量化 | OOM 再上 |

**加速**(实测倍率,[PyTorch](https://pytorch.org/blog/peak-performance-minimized-memory/) · [Chronicals](https://arxiv.org/html/2601.02609v1)):flash-attn 1.9x · torch.compile 1.5x · Liger 1.4x(+20% throughput,单项最大贡献 38%)· sequence packing 1.2x · fused optimizer 1.07x。
- **我们最该上**:flash-attn + gradient checkpointing + Liger + **按长度分桶 batching**(长尾严重,不分桶浪费大量 padding)。
- **sequence packing**:省 padding 但和多轮 loss-mask + 32k 单条长样本冲突(单条没法拆 block),跳过或很小心做。
- **坑**:别盲目叠——Liger×torch.compile 可能打架、量化破坏收敛、packing 要自定义 mask;**加一个验一个**。

**最小稳妥组合(2×A800/8B LoRA/32k)**:bf16 + flash-attn + gradient checkpointing + FSDP(优化器 offload)+ Liger + 长度分桶;packing/torch.compile 选配。
