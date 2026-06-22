# SFT 热启动可执行方案(chatloop 工具调用 agent → GRPO)

> 由 SFT 调研 workflow(4 路并行 web 调研 + 读项目代码 + 合成)产出。**基座 Qwen3-8B-Thinking(见下「决策更新」——优先级高于正文里的 no-think / Instruct 表述)**,路线 SFT 热启动 → GRPO + indicator_oracle 可验证奖励。术语见正文。

## 已确认的项目事实(研究 agent 读代码核验)

- `arguments` 存成 JSON 字符串 → 命中 Qwen3 模板 string 透传,不会二次转义。
- assistant 消息**无 reasoning/`<think>`**(`state.py:176`)→ 轨迹 think-free。
- collect 模式 `downgrade_char_threshold=10**9`(`runner.py:90`)→ 保留完整工具输出(SFT 好,但序列长)。
- `data_refs`:run_python 按短 ref 引用缓存数据,非内联数组(`loop.py:299` 大输出换 digest+ref)。

## 决策更新(2026-06-22,据业务场景重定 — 优先级高于下方 ⑤ 存疑点)

业务定调:本项目是**金融指标计算 agent**,核心难点 = run_python 写对算法;踩过的 badcase 全是**推理性口径错**(回撤路径依赖 / 复权口径 / 多序列对齐),不是格式错;且为个人作品,**延迟/成本非约束**。据此两个关键决策,**明确不走"省事"默认**:

**决策 A — 开 think,基座换 Thinking。** 理由:① 算指标要先想清楚口径/公式/路径依赖,边想边写才不犯口径错;② 失败模式是推理错——不带 think 会复刻捷径,带 think 能"等一下,回撤得扫累计序列"纠回来;③ **RLVR 只放大已有推理链,不带 think 模式无推理草稿可放大 → 算法正确性的 RL 天花板被结构性锁死**;④ 作品要体现技术深度,延迟非约束,"省事"三理由(简单/快/数据现成)对本项目全是弱理由。
- **基座**:Qwen3-8B-**Thinking**-2507(或 hybrid 开 thinking),非 Instruct 支。
- **SFT 数据要带推理草稿**:deepseek-v4-flash 不带 think,**换思考型最强 teacher**(承「用最强模型标注 SFT」决策:DeepSeek-R1 / Qwen3-Thinking / 更强推理模型)。**teacher 必须在 chatloop 内产轨迹**(格式与 qwen3-8b 上场一致);Qwen3-Thinking 经 dashscope `enable_thinking=true` 可直接接,DeepSeek-R1 要先确认工具调用可用。
- **走 R1 配方**:少量高质量推理轨迹**冷启**(把"先想再动手"格式种进去),真正的推理质量靠 **GRPO 长出来**(RLVR 放大推理链)——所以 think 的数据成本没想象中吓人。
- **不带 think 版降为对照组**,用来量化 think 带来的算法正确性提升(本身是有深度的实验结论)。

**决策 B — SFT 采集对齐推理形态(开降级,不是关)。** 之前 collect 设 `downgrade_char_threshold=10**9` 关降级=保全完整行情内联,会造成"训练整串内联 / 推理 `data_refs` 短引用"的**形态错位**(用 A 课本复习拿 B 课本考)。修正:**采 SFT 数据时降级开着、跟真推理一致**——训练样本里也是"短引用+摘要",模型学的就是"看编号 → 写 run_python 用编号"。**这要改 Task 3 collect 的默认值**(不再设 10**9,改用推理同款阈值)。think + 形态对齐两件事一起满足。

> 影响:下方 ① 的「数据格式」「训哪几轮」「SFT→RL 交接」凡涉及 no-think 的论断,按本决策读作"带 think";②「已有 vs 还要补」里"轨迹无 think"由优势改为"要重采带 think 轨迹";③ 步骤清单的"采数据"改为"用思考型 teacher 采、降级开着"。

## ① 具体 SFT 配方

### 数据格式:基本不动,一个项目特有的坑
runner 落盘就是标准 OpenAI 多轮 messages + tools 快照,TRL `SFTTrainer` 直接吃。但轨迹**无 think**改变三件事:① 不用操心 Qwen3 多轮剥历史 `<think>` 的坑(简化);② 但 run_python"为什么这么算"没被监督(存疑点⑤-1);③ **SFT 与推理的 chat template 必须字节级一致**——推理若开 `enable_thinking`,Qwen3 会强行吐空 `<think></think>`,训练数据没有 → 错位,必须先对齐。

### loss 掩码:唯一真正要做对的活
铁律:**只在 assistant 自己生成的 token 上算 loss,其余全 mask 成 `-100`**。

| 段落 | 算 loss | 为什么 |
|---|---|---|
| assistant content + `<tool_call>` JSON(含 run_python code) | ✅ | 推理时模型要自己写 |
| tool 结果(行情、run_python stdout) | ❌ | 环境给的,算 loss 会背行情数字/学幻觉输出 |
| user / system / tools 定义 | ❌ | 给定上下文;**保留在序列里**但不算 loss |

坑:Qwen3 模板把 `role:tool` 渲进 `<|im_start|>user` 块(`<tool_response>` 包)——本就该 mask,**别因"内容来自工具"手贱给它算 loss**。
实现三选一(按"框架最小化"偏好排序):**① 自己写 tokenize 产 labels(推荐,且 GRPO 要复用同一份)**;② 改模板加 `{% generation %}` + TRL `assistant_only_loss=True`(Qwen3 官方模板**默认不带此标记,直接开会静默失效**);③ Axolotl(内置 Qwen3 input masking)。
**必做验证**:渲一条打印 `labels`,肉眼确认 tool/user/`<tool_response>` 全 -100,只有 assistant content + tool_call JSON 是真 id。

### 训哪几轮:训所有 assistant 轮(路线 A 全轨迹掩码)
核心价值=多步编排能力,只在中间轮,只训收尾=没训 agent。轨迹无 think 让"路线 B 拆单轮"的唯一优势(对齐剥历史 think)失效,所以选**路线 A**:更省算力、更简单。

### 数据量:几百条独立干净轨迹即可
热启动是千条量级,不是十万(R1 cold-start=thousands;LIMA 1000 条即对齐)。盯"去重后独立干净轨迹数",目标 **≳ 几百条**。例外:run_python 偏数学/代码域,是少数"加数据不见顶"的场景(代码质量上不去时唯一能靠加数据涨的地方)。k=5~8 起步(收集"不同但都对"的解法,非复制粘贴),别盲目到 20。

### 质量筛选:你有别人没有的奢侈品——oracle
现在只筛 `halt_reason==natural`(最弱一层)。补两级:**① 结果对**:按 `case_id` join trajectories_raw + judgements,只留 `passed==true`(确定性过滤,比大模型裁判强);**② 过程干净**:砍绕路/超调、run_python 代码烂、messages 结构不合法(tool_call 与结果未配对);**③ 去重**:题面语义 + 工具调用序列签名两层,每簇留 1~2 条。

### 框架:正式训用 verl 自带 `fsdp_sft_trainer`
与后续 GRPO(`main_ppo`)同仓同 FSDP,checkpoint 存 HF 格式**直通 GRPO 当 actor+reference,零转换**。数据组织/掩码自己写,训练循环交 verl。TRL/LLaMA-Factory 仅用于小规模格式冒烟。

### 超参起点(先 LoRA 跑通整条链)
LR **1e-4**(LoRA)/ rank **16~32** alpha **32~64** / epochs **2~3**(宁少勿多)/ 有效 batch **32~64** / cosine warmup 0.1 / BF16 / max_seq **先按轨迹 p95 定,4096 起,溢出 8192**(collect 关降级 → 序列长,**务必先统计长度分布**)/ packing **开 + position-id 隔离**(以整条轨迹为最小单位,别把一条拆两 pack)。参照:Qwen3-8B SFT+GRPO 实战(verl, LoRA rank32, 2 epoch)。

### SFT→RL 交接(决定 SFT 帮不帮 GRPO)
**反直觉:SFT 做过头会拖垮 GRPO**——ToolRL 实测冷启 GRPO 反超 SFT 初始化 **22 点**;SFT-then-GRPO 平均掉 12.7%。机制:SFT 压塌熵 → GRPO 组内采样同质 → advantage≈0 → 涨不动。**但别误读成别做 SFT**:base 若几乎采不到全对轨迹,冷启 GRPO 奖励全 0 启动不了。SFT 价值=把成功率从≈0 抬到 RL 撞得到,然后停。
五条硬约束:① **故意做小、早停、欠拟合**(只教格式+多步结构,不教推理);② **选 checkpoint 用 hold-out Pass@64 + 泛化 loss,不用 train loss / Pass@1**(Post-SFT Pass@1 预测力 R²≈0.4,Pass@64 R²≈0.94);监控 token 熵别塌;③ **SFT 落盘 mask / GRPO 算 log-prob / 推理 三处 token 边界与 mask 规则逐字节一致,共用一份函数**;④ **必做对照组**:base 直接 GRPO 不 SFT;⑤ **开 GRPO 前组内方差体检**:SFT checkpoint 对训练题各采一组,统计"组内有对有错"比例(全对=SFT 过了锁死,全错=太难/太弱,都涨不动)。
奖励提示:ToolRL 把奖励拆"格式 + 三档正确性",比二元丰富;考虑把 oracle 拆成"工具链/run_python 算法/最终值"几档缓解稀疏 stall。

## ② 已经有的 vs 还要补的

**已有(强起点)**:标准格式轨迹(collect 模式,无 gold,natural halt)· 确定性 oracle(6 冻结口径)· 已关 context downgrade · 轨迹与 gold 物理隔离(case_id join)· arguments 是 JSON 字符串 · 轨迹无 think · 采集层已 error-masking。
**还要补**:拒绝采样筛选脚本(oracle 结果筛,现在没用)· 去重脚本 · tokenize+labels 生成器(GRPO 复用)· chat template 对齐确认 · 轨迹长度分布统计 · hold-out 评估集 · 更多采样轨迹(独立轨迹不足几百条时补)· verl 环境。

## ③ 到能开 SFT 的步骤清单
1 采数据(collect, k5~8)→ 2 拒绝采样筛(join 留 passed)→ 3 过程清洗 → 4 去重 → 5 长度分布 → 6 数独立轨迹数(不足回 1)→ 7 对齐 chat template → 8 写 tokenize+labels(渲一条肉眼验,标"GRPO 复用")→ 9 切 hold-out → 10 小规模冒烟 → 11 搭 verl → 12 正式 SFT(LoRA)→ 13 选 checkpoint(Pass@64+泛化 loss+熵,非 train loss)→ 14 组内方差体检 → 15(并行)base 直接 GRPO 对照组 → 16 交接 GRPO(checkpoint 直通,复用 mask)。

## ⑤ 仍存疑、需你定的点
1. ~~轨迹无 think 够不够~~ → **✅ 已定(决策 A)**:据业务场景(算指标是推理活、失败模式是口径错、RL 上限需推理草稿)**决定开 think**,基座换 Thinking,SFT 用思考型 teacher 采带推理轨迹,不带 think 降为对照组。
2. ~~collect 关降级 → 形态错位~~ → **✅ 已定(决策 B)**:**采 SFT 数据时降级开着、与推理一致**(`data_refs` 短引用形态),改 Task 3 collect 默认值,不再设 10**9。
3. **141 道幸存者偏差**:deepseek 通过的偏简单,难题轨迹缺失,SFT 喂不进难题能力。**需定**:要不要更强 teacher 啃难题补轨迹(注意 teacher 天花板)。
4. **LoRA vs 全参**:先 LoRA,跑通看 Pass@64 决定要不要全参重跑。
5. **GRPO 奖励要不要拆多档**(ToolRL 风格):奖励 schema 现在定能少返工。
6. **k 取多少 / 救不救难题**:采完一轮数出独立轨迹数才能定。

## 关键来源
- 掩码:[TRL SFTTrainer](https://huggingface.co/docs/trl/v0.20.0/en/sft_trainer) · [Qwen3-8B discussion #14](https://huggingface.co/Qwen/Qwen3-8B/discussions/14) · [Qwen3 chat template deep dive](https://huggingface.co/blog/qwen-3-chat-template-deep-dive) · [froggeric Qwen-Fixed-Templates](https://huggingface.co/froggeric/Qwen-Fixed-Chat-Templates)
- 数据量/质量:[DeepSeek-R1](https://arxiv.org/html/2501.12948v1) · [LIMA/数据基础](https://cameronrwolfe.substack.com/p/data-is-the-foundation-of-language) · [Rejection Sampling FT](https://www.emergentmind.com/topics/rejection-sampling-fine-tuning-rsft)
- 框架/超参:[verl fsdp_sft_trainer](https://github.com/volcengine/verl/blob/main/verl/trainer/fsdp_sft_trainer.py) · [verl checkpoint 直通](https://verl.readthedocs.io/en/latest/advance/checkpoint.html) · [Qwen3-8B SFT+GRPO 实战](https://dtianyou.com/en/notes/qwen3-8b-base-training/) · [Packing with FA2](https://huggingface.co/blog/packing-with-FA2)
- SFT→RL 交接(最该读):[ToolRL](https://lifelongagent.github.io/Project-Lifelong-Agent/ToolRL/index.html) · [Lightweight SFT for RL(Pass@64 选点)](https://openreview.net/forum?id=yezWGJmODg) · [RL Squeezes SFT Expands](https://arxiv.org/html/2509.21128v2) · [SFT-then-GRPO 掉点](https://arxiv.org/html/2504.11468v1) · [RC-GRPO stall 诊断](https://arxiv.org/html/2602.03025)
